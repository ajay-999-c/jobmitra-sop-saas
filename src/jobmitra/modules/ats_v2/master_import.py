"""Append-only, source-ID based master import with checked SQLite backups."""

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from .common import utc_now
from .database import CORE_TABLES, upgrade, validate
from .master_mapping import map_candidate, map_company, map_resume_metadata, source_fingerprint
from .master_source import canonical
from .resumes import safe_resume_path

RESUME_TABLES = ("candidate_documents", "candidate_resumes", "resume_parse_results")


class ImportConflict(Exception):
    pass


def stable_integer(table, source_id):
    # Safe in both SQLite INTEGER and JavaScript Number; do not truncate 64-bit IDs in the UI.
    return int(hashlib.sha256((table + ":" + source_id).encode()).hexdigest()[:12], 16) or 1


def local_state(conn):
    tables = set(
        conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).scalars()
    )
    return {
        table: [
            dict(row) for row in conn.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()
        ]
        for table in sorted(tables)
        if table in CORE_TABLES | {"companies"}
    }


def state_counts(state):
    return {name: len(rows) for name, rows in state.items()}


def file_probe(row, source_table, source_root):
    if source_table == "resume_parse_results":
        return {"status": "metadata_only", "path": None}
    key = row.get("storage_key")
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}\.(pdf|docx)", key):
        return {"status": "unsafe_source_reference", "path": None}
    if source_root is None:
        return {"status": "source_root_unconfigured", "path": None}
    root = Path(source_root).expanduser()
    if not root.is_absolute() or not root.is_dir():
        return {"status": "source_root_unavailable", "path": None}
    root = root.resolve()
    path = root / key
    if path.is_symlink() or path.resolve().parent != root:
        return {"status": "unsafe_source_reference", "path": None}
    if not path.is_file():
        return {"status": "missing", "path": None}
    expected = row.get("sha256") if source_table == "candidate_documents" else row.get("file_hash")
    size = row.get("size_bytes") if source_table == "candidate_documents" else row.get("file_size")
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if path.stat().st_size != size or actual != expected:
        return {"status": "hash_mismatch", "path": None}
    return {"status": "ready_to_copy", "path": path, "sha256": expected, "size": size}


def plan_import(source, state, *, companies=True, candidates=True, source_root=None):
    tables = source["tables"]
    plan = {
        "companies": [],
        "candidates": [],
        "resumes": [],
        "conflicts": [],
        "warnings": [],
        "existing": {"companies": 0, "candidates": 0, "resumes": 0},
        "source_counts": source["counts"],
        "before_counts": state_counts(state),
    }
    local_companies = state.get("companies", [])
    local_candidates = state.get("candidates", [])
    local_resumes = state.get("candidate_resumes", [])
    company_ids = {r["id"]: r for r in local_companies}
    company_sources = {
        r.get("legacy_postgres_id"): r for r in local_companies if r.get("legacy_postgres_id")
    }
    company_keys = {r["company_name_key"]: r for r in local_companies}
    candidate_ids = {r["id"]: r for r in local_candidates}
    candidate_sources = {
        r.get("legacy_postgres_id"): r for r in local_candidates if r.get("legacy_postgres_id")
    }
    candidate_codes = {r["candidate_code"]: r for r in local_candidates if r["candidate_code"]}
    resume_ids = {r["id"]: r for r in local_resumes}
    resume_sources = {
        (r.get("legacy_source_table"), r.get("legacy_postgres_id")): r
        for r in local_resumes
        if r.get("legacy_postgres_id")
    }
    identities = defaultdict(set)
    for row in local_candidates:
        for key in ("phone_normalized", "email_normalized"):
            if row.get(key):
                identities[(key, row[key])].add(
                    row.get("legacy_postgres_id") or "local:" + str(row["id"])
                )

    def issue(table, identifier, code, *, blocking=True):
        plan["conflicts" if blocking else "warnings"].append(
            {"source_table": table, "source_id": identifier, "code": code}
        )

    def mapped(result, table, identifier):
        for code in result.issues:
            issue(table, identifier, code, blocking=code in result.blocking_issues)
        return result.valid

    if companies:
        for row in sorted(tables.get("companies", []), key=lambda r: r["id"]):
            result = map_company(row, tables.get("company_contacts", []))
            if not mapped(result, "companies", row["id"]):
                continue
            values = result.values
            existing = company_sources.get(row["id"])
            if existing:
                plan["existing"]["companies"] += 1
                if existing.get("source_fingerprint") != values["source_fingerprint"]:
                    issue("companies", row["id"], "source_changed_existing_company_not_overwritten")
                continue
            if values["id"] in company_ids:
                issue("companies", row["id"], "company_primary_key_conflict")
                continue
            if values["company_name_key"] in company_keys:
                issue("companies", row["id"], "possible_duplicate_company_name")
                continue
            company_ids[values["id"]] = values
            company_keys[values["company_name_key"]] = values
            company_sources[row["id"]] = values
            plan["companies"].append(values)

    if candidates:
        for row in sorted(tables.get("candidates", []), key=lambda r: r["id"]):
            result = map_candidate(
                row, tables.get("work_domains", []), tables.get("work_subdomains", [])
            )
            if not mapped(result, "candidates", row["id"]):
                continue
            values = result.values
            existing = candidate_sources.get(row["id"])
            if existing:
                plan["existing"]["candidates"] += 1
                if existing.get("source_fingerprint") != values["source_fingerprint"]:
                    issue(
                        "candidates", row["id"], "source_changed_existing_candidate_not_overwritten"
                    )
                continue
            values["id"] = stable_integer("candidates", row["id"])
            if values["id"] in candidate_ids or values["candidate_code"] in candidate_codes:
                issue("candidates", row["id"], "candidate_primary_key_or_code_conflict")
                continue
            matches = set()
            for key in ("phone_normalized", "email_normalized"):
                if values.get(key):
                    matches.update(identities[(key, values[key])])
            if matches - {row["id"]}:
                if any(value.startswith("local:") for value in matches):
                    issue("candidates", row["id"], "possible_duplicate_candidate_identity")
                    continue
                # Distinct source PKs are distinct legacy records. Copy each once;
                # contact normalization must never silently merge their identities.
                issue(
                    "candidates",
                    row["id"],
                    "possible_duplicate_source_identity_preserved",
                    blocking=False,
                )
            candidate_ids[values["id"]] = values
            candidate_codes[values["candidate_code"]] = values
            candidate_sources[row["id"]] = values
            for key in ("phone_normalized", "email_normalized"):
                if values.get(key):
                    identities[(key, values[key])].add(row["id"])
            values["search_text"] = " ".join(
                str(values.get(key) or "")
                for key in (
                    "job_title",
                    "current_employer",
                    "qualification",
                    "professional_summary",
                    "skills_json",
                )
            ).casefold()
            plan["candidates"].append(values)

        for table in RESUME_TABLES:
            for row in sorted(tables.get(table, []), key=lambda r: r["id"]):
                result = map_resume_metadata(row, table, tables.get("candidate_documents", []))
                if not mapped(result, table, row["id"]):
                    continue
                values = dict(result.values)
                values.pop("source_fingerprint", None)
                existing = resume_sources.get((table, row["id"]))
                if existing:
                    plan["existing"]["resumes"] += 1
                    if source_fingerprint(existing.get("source_json") or "") != source_fingerprint(
                        values["source_json"]
                    ):
                        issue(table, row["id"], "source_changed_existing_resume_not_overwritten")
                    continue
                candidate = candidate_sources.get(result.references.get("candidate_id"))
                if not candidate:
                    issue(table, row["id"], "resume_candidate_not_mapped")
                    continue
                values.update(id=stable_integer(table, row["id"]), candidate_id=candidate["id"])
                if values["id"] in resume_ids:
                    issue(table, row["id"], "resume_primary_key_conflict")
                    continue
                probe = file_probe(row, table, source_root)
                if probe["status"] not in {"ready_to_copy", "metadata_only"}:
                    issue(table, row["id"], "resume_file_" + probe["status"], blocking=False)
                if table != "resume_parse_results":
                    metadata = json.loads(values["parsed_json"])
                    metadata["migration_file_status"] = (
                        "copied" if probe["status"] == "ready_to_copy" else probe["status"]
                    )
                    values["parsed_json"] = canonical(metadata)
                # Preserve source bodies privately; audit events contain metadata only.
                if table == "candidate_resumes" and row.get("extracted_text"):
                    values["raw_text"] = row["extracted_text"]
                entry = {"values": values, "probe": probe, "source": row, "source_table": table}
                resume_ids[values["id"]] = values
                plan["resumes"].append(entry)

        # Preserve native/current versions. Select only a copied, explicit source current original
        # or, if absent, the latest version from the legacy versioned-document path.
        groups = defaultdict(list)
        occupied = {(r["candidate_id"], r["resume_kind"]) for r in local_resumes if r["is_current"]}
        for entry in plan["resumes"]:
            if entry["probe"]["status"] == "ready_to_copy":
                groups[(entry["values"]["candidate_id"], entry["values"]["resume_kind"])].append(
                    entry
                )
        for key, entries in groups.items():
            if key in occupied:
                continue
            explicit = [
                e
                for e in entries
                if e["source_table"] == "candidate_resumes" and e["source"].get("is_active")
            ]
            versioned = [e for e in entries if e["source_table"] == "candidate_documents"]
            choices = explicit or versioned
            if choices:
                chosen = max(
                    choices,
                    key=lambda e: (
                        e["values"]["created_at"],
                        e["source"].get("version", 0),
                        e["values"]["id"],
                    ),
                )
                chosen["values"]["is_current"] = 1

    for job in state.get("job_descriptions", []):
        if job["company_id"] not in company_ids:
            issue("job_descriptions", str(job["id"]), "existing_jd_company_not_mapped")
    return plan


def plan_report(plan):
    files = Counter(entry["probe"]["status"] for entry in plan["resumes"])
    return {
        "source_counts": plan["source_counts"],
        "before_counts": plan["before_counts"],
        "ready": {key: len(plan[key]) for key in ("companies", "candidates", "resumes")},
        "already_imported": plan["existing"],
        "conflicts": plan["conflicts"],
        "conflict_codes": dict(Counter(item["code"] for item in plan["conflicts"])),
        "warning_codes": dict(Counter(item["code"] for item in plan["warnings"])),
        "warnings": plan["warnings"],
        "resume_file_plan": dict(files),
    }


def backup_database(database, directory):
    database, directory = Path(database).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = directory / (f"ats-before-master-import-{stamp}-{uuid4().hex[:8]}.sqlite3")
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
            # Produce a self-contained backup, without leaving destination WAL handles open.
            destination.execute("PRAGMA journal_mode=DELETE")
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ImportConflict("SQLite backup integrity check failed.")
            if destination.execute("PRAGMA foreign_key_check").fetchall():
                raise ImportConflict("SQLite backup has broken foreign keys.")
    return backup


def preserve_existing(conn, before):
    for table, rows in before.items():
        for original in rows:
            current = (
                conn.execute(text(f"SELECT * FROM {table} WHERE id=:id"), {"id": original["id"]})
                .mappings()
                .first()
            )
            if current is None or any(current[key] != value for key, value in original.items()):
                raise ImportConflict(
                    "An existing SQLite record changed; the transaction was rolled back."
                )


def integrity(conn):
    if conn.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
        raise ImportConflict("SQLite integrity check failed.")
    if conn.exec_driver_sql("PRAGMA foreign_key_check").first():
        raise ImportConflict("SQLite foreign-key check failed.")
    if conn.scalar(
        text(
            "SELECT count(*) FROM job_descriptions j LEFT JOIN companies c "
            "ON c.id=j.company_id WHERE c.id IS NULL"
        )
    ):
        raise ImportConflict("A JD company reference is unresolved.")


def insert(conn, table, values):
    conn.execute(
        text(
            f"INSERT INTO {table} ({','.join(values)}) VALUES ("
            + ",".join(":" + key for key in values)
            + ")"
        ),
        values,
    )
    actual = (
        conn.execute(text(f"SELECT * FROM {table} WHERE id=:id"), {"id": values["id"]})
        .mappings()
        .one()
    )
    for key, value in values.items():
        found = actual[key]
        if key.endswith("_salary_inr") and value is not None:
            if Decimal(str(found)) == Decimal(str(value)):
                continue
        if found != value:
            raise ImportConflict("An imported field did not round-trip; transaction rolled back.")


def copy_resume(entry, storage_root, created_files):
    if entry["probe"]["status"] != "ready_to_copy":
        return
    values, probe = entry["values"], entry["probe"]
    suffix = probe["path"].suffix.lower()
    relative = f"imports/{entry['source_table']}/{values['legacy_postgres_id']}{suffix}"
    destination = safe_resume_path(storage_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        raise ImportConflict(
            "An unregistered destination resume already exists; no file was overwritten."
        )
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    created_files.append(destination)
    size, digest = 0, hashlib.sha256()
    with os.fdopen(fd, "wb") as output, probe["path"].open("rb") as original:
        while chunk := original.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        output.flush()
        os.fsync(output.fileno())
    if size != probe["size"] or digest.hexdigest() != probe["sha256"]:
        raise ImportConflict("A source resume changed during copying; no import was committed.")
    values["storage_path"] = relative


def execute_import(
    engine,
    source,
    *,
    backup_directory,
    storage_root,
    source_root=None,
    companies=True,
    candidates=True,
    source_verifier=None,
):
    validate(engine, allow_v1=True)
    created_files = []
    report = {"mode": "execute", "source_fingerprint": source["source_fingerprint"]}
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                before = local_state(conn)
                plan = plan_import(
                    source,
                    before,
                    companies=companies,
                    candidates=candidates,
                    source_root=source_root,
                )
                report.update(plan_report(plan))
                if plan["conflicts"]:
                    raise ImportConflict(
                        "Unresolved import conflicts; no records were overwritten."
                    )
                version = conn.exec_driver_sql("PRAGMA user_version").scalar_one()
                ready = sum(len(plan[key]) for key in ("companies", "candidates", "resumes"))
                if version == 1 or ready:
                    report["backup"] = str(
                        backup_database(Path(engine.url.database), backup_directory)
                    )
                    upgrade(conn)
                    imported_at = utc_now()
                    for table in ("companies", "candidates"):
                        for values in plan[table]:
                            insert(conn, table, {**values, "imported_at": imported_at})
                    for entry in plan["resumes"]:
                        copy_resume(entry, storage_root, created_files)
                        insert(
                            conn,
                            "candidate_resumes",
                            {**entry["values"], "imported_at": imported_at},
                        )
                else:
                    report["backup"] = None
                integrity(conn)
                preserve_existing(conn, before)
                after = local_state(conn)
                verification = plan_import(
                    source,
                    after,
                    companies=companies,
                    candidates=candidates,
                    source_root=source_root,
                )
                if verification["conflicts"] or any(
                    verification[key] for key in ("companies", "candidates", "resumes")
                ):
                    raise ImportConflict(
                        "Source-ID reconciliation failed; no import was committed."
                    )
                if source_verifier is not None:
                    checked = source_verifier()
                    if checked["source_fingerprint"] != source["source_fingerprint"]:
                        raise ImportConflict(
                            "PostgreSQL source changed during import; retry a fresh dry run."
                        )
                    report["source_after_counts"] = checked["counts"]
                    report["source_unchanged"] = True
                report.update(
                    after_counts=state_counts(after),
                    imported={
                        key: len(plan[key]) for key in ("companies", "candidates", "resumes")
                    },
                    copied_files=len(created_files),
                    existing_records_preserved=True,
                    integrity_check="ok",
                    foreign_key_check="ok",
                    source_id_reconciliation="ok",
                    rerun_ready={
                        key: len(verification[key])
                        for key in ("companies", "candidates", "resumes")
                    },
                    status="verified",
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
    except BaseException:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise
    return report

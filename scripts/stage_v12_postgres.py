"""Import a verified SQLite backup into an immutable, isolated PostgreSQL snapshot.

This is deliberately not an application database adapter. Existing public objects are
only read. A known, identical snapshot may be verified again; conflicts never update
or replace records. The CLI requires the independently restored backup gate.
"""

import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from jobmitra.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "jobmitra_v12_stage"
# Assigned source-store identity, independent of run ID, path and snapshot contents.
SOURCE_STORE_ID = UUID("7fae8143-a35e-47f2-aef8-04f78879b4ec")
MIGRATION = ROOT / "migrations/v12_postgres/001_stage.sql"
CONTRACT = ROOT / "migrations/v12_postgres/001_source_contract.json"
SALARIES = {"current_salary_inr", "expected_salary_inr", "salary_min_inr", "salary_max_inr"}
DEV_CANDIDATES = {
    "Preview Candidate · Asha",
    "UI Verification Candidate Nov20",
    "UI Verification Closure Nov20",
}
DEV_COMPANIES = {
    "Preview · Example Studio",
    "UI Verification Client Nov20",
    "Proposal Verification Client Nov20",
}


class MigrationConflict(RuntimeError):
    """A backup, source, destination or reconciliation safety gate failed."""


def require(condition, message):
    if not condition:
        raise MigrationConflict(message)


def sha_file(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def canonical(row):
    result = dict(row)
    for column in SALARIES & result.keys():
        if result[column] is not None:
            result[column] = {"decimal": format(Decimal(str(result[column])).normalize(), "f")}
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def row_sha(row):
    return hashlib.sha256(canonical(row).encode()).hexdigest()


def read_source(path):
    contract = json.loads(CONTRACT.read_text())
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        require(conn.execute("PRAGMA user_version").fetchone()[0] == 3, "Expected SQLite V3")
        require(
            conn.execute("PRAGMA application_id").fetchone()[0] == 1246576980,
            "Unexpected SQLite application identity",
        )
        require(
            [r[0] for r in conn.execute("PRAGMA integrity_check")] == ["ok"],
            "SQLite integrity failure",
        )
        require(not conn.execute("PRAGMA foreign_key_check").fetchall(), "SQLite FK failure")
        actual = dict(
            conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        require(set(actual) == set(contract["tables"]), "SQLite table contract drift")
        rows = {}
        for table, definition in contract["tables"].items():
            require(
                hashlib.sha256(actual[table].encode()).hexdigest()
                == definition["sqlite_ddl_sha256"],
                f"SQLite DDL drift: {table}",
            )
            rows[table] = [dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY id')]
        views = {
            v: [dict(r) for r in conn.execute(f'SELECT * FROM "{v}"')] for v in contract["views"]
        }
    for table, records in rows.items():
        for record in records:
            require(
                not any(isinstance(v, str) and "\x00" in v for v in record.values()),
                f"PostgreSQL cannot represent a text NUL: {table}",
            )
            for key, value in record.items():
                if key.endswith("_json") and value is not None:
                    json.loads(value, parse_float=Decimal)
                if value is not None and isinstance(value, str):
                    if key.endswith(("_at", "_at_utc")):
                        datetime.fromisoformat(value.replace("Z", "+00:00"))
                    elif key.endswith("_on") or key in {
                        "target_date",
                        "issue_date",
                        "effective_date",
                    }:
                        date.fromisoformat(value)
            if table == "candidates":
                origin = json.loads(record["source_json"] or "{}", parse_float=Decimal)
                for key, source_key in [
                    ("current_salary_inr", "current_salary_amount"),
                    ("expected_salary_inr", "expected_salary_amount"),
                ]:
                    value = record[key]
                    if value is not None:
                        amount = Decimal(str(value))
                        require(amount.is_finite() and amount >= 0, "Invalid salary")
                        if origin.get(source_key) is not None:
                            require(
                                amount == Decimal(str(origin[source_key])),
                                "Source salary/provenance discrepancy",
                            )
                            record[key] = Decimal(str(origin[source_key]))
    return rows, views


def public_fingerprint(conn):
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
    ]
    # One SQL statement gives all row fingerprints the same MVCC snapshot.
    query = sql.SQL(" UNION ALL ").join(
        [
            sql.SQL("SELECT {}::text, row_to_json(t)::text FROM public.{} t").format(
                sql.Literal(t), sql.Identifier(t)
            )
            for t in tables
        ]
    )
    rows = {t: [] for t in tables}
    for table, payload in conn.execute(query):
        rows[table].append(payload)
    return {
        t: {
            "count": len(values),
            "sha256": hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest(),
        }
        for t, values in rows.items()
    }


def fingerprint_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def classify(rows, baseline_path):
    """Only explicitly reviewed fixtures and their proven dependants are test data."""
    dev_candidates = {r["id"] for r in rows["candidates"] if not r["legacy_postgres_id"]}
    dev_companies = {r["id"] for r in rows["companies"] if not r["legacy_postgres_id"]}
    require(
        {r["full_name"] for r in rows["candidates"] if r["id"] in dev_candidates} == DEV_CANDIDATES,
        "Unreviewed unmapped candidate; classification required",
    )
    require(
        {r["company_name"] for r in rows["companies"] if r["id"] in dev_companies} == DEV_COMPANIES,
        "Unreviewed unmapped company; classification required",
    )
    dev_jobs = {r["id"] for r in rows["job_descriptions"] if r["company_id"] in dev_companies}
    require(len(dev_jobs) == len(rows["job_descriptions"]), "Unreviewed JD classification")
    with sqlite3.connect(Path(baseline_path).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        baseline_tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        baseline = {
            t: {r["id"]: dict(r) for r in conn.execute(f'SELECT * FROM "{t}"')}
            for t in baseline_tables
        }
    result = {}
    for table, records in rows.items():
        for row in records:
            key = (table, str(row["id"]))
            old = baseline.get(table, {}).get(row["id"])
            if old is not None:
                require(
                    row_sha({k: row[k] for k in old}) == row_sha(old),
                    f"Original V2 row changed: {table}",
                )
                result[key] = ("IMPORTED_LEGACY", "Byte-preserved field values of original V2 row")
            else:
                is_dev = (
                    (table == "candidates" and row["id"] in dev_candidates)
                    or (table == "companies" and row["id"] in dev_companies)
                    or row.get("candidate_id") in dev_candidates
                    or row.get("company_id") in dev_companies
                    or row.get("job_id") in dev_jobs
                )
                if table in {"company_proposal_signed_documents", "company_proposal_status_events"}:
                    is_dev = any(
                        p["id"] == row["proposal_id"] and p["company_id"] in dev_companies
                        for p in rows["company_proposals"]
                    )
                require(is_dev, f"Unreviewed new row: {table}")
                result[key] = ("DEVELOPMENT_TEST", "Reviewed isolated preview fixture/descendant")
    for table, old in baseline.items():
        require(set(old) <= {r["id"] for r in rows[table]}, f"Missing original V2 row: {table}")
    return result


def verify_legacy_identities(conn, rows):
    maps = {}
    for table in [
        "candidates",
        "companies",
        "company_contacts",
        "candidate_resumes",
        "candidate_documents",
        "resume_parse_results",
    ]:
        maps[table] = {
            str(r[0])
            for r in conn.execute(sql.SQL("SELECT id FROM public.{}").format(sql.Identifier(table)))
        }
    counts = {}
    candidate_map = {r["id"]: r["legacy_postgres_id"] for r in rows["candidates"]}
    for table in ["candidates", "companies"]:
        ids = [r["legacy_postgres_id"] for r in rows[table] if r["legacy_postgres_id"]]
        require(len(ids) == len(set(ids)), "Duplicate legacy master identity")
        require(
            all(str(UUID(i)) == i and i in maps[table] for i in ids),
            f"Invalid/missing legacy identity: {table}",
        )
        counts[table] = len(ids)
    contacts = 0
    with conn.cursor(row_factory=dict_row) as cur:
        for row in rows["companies"]:
            for contact in json.loads(row["contacts_json"]):
                if row["legacy_postgres_id"]:
                    cur.execute(
                        "SELECT company_id FROM public.company_contacts WHERE id=%s",
                        (UUID(contact["id"]),),
                    )
                    parent = cur.fetchone()
                    require(
                        parent and str(parent["company_id"]) == row["legacy_postgres_id"],
                        "Contact legacy parent mismatch",
                    )
                    contacts += 1
        resumes = 0
        for row in rows["candidate_resumes"]:
            if row["legacy_postgres_id"]:
                table = row["legacy_source_table"]
                require(
                    table in {"candidate_resumes", "candidate_documents", "resume_parse_results"},
                    "Unapproved resume provenance",
                )
                cur.execute(
                    sql.SQL("SELECT * FROM public.{} WHERE id=%s").format(sql.Identifier(table)),
                    (UUID(row["legacy_postgres_id"]),),
                )
                parent = cur.fetchone()
                require(parent is not None, "Missing legacy resume identity")
                if table == "resume_parse_results":
                    cur.execute(
                        "SELECT candidate_id FROM public.candidate_documents WHERE id=%s",
                        (parent["document_id"],),
                    )
                    parent = cur.fetchone()
                require(
                    parent and str(parent["candidate_id"]) == candidate_map[row["candidate_id"]],
                    "Resume legacy parent mismatch",
                )
                resumes += 1
    return {**counts, "contacts": contacts, "resumes": resumes}


def validate_backup_gate(directory):
    directory = Path(directory).resolve()
    require(not directory.is_relative_to(ROOT), "Backups must be outside Git/application runtime")
    manifest = json.loads((directory / "backup-verification.json").read_text())
    require(
        manifest.get("verified") and manifest["restore"]["result"] == "passed",
        "Backup restore gate not satisfied",
    )
    require(
        manifest["restore"]["all_public_table_counts_and_full_row_fingerprints_match"],
        "Backup restore reconciliation missing",
    )
    age = datetime.now(UTC) - datetime.fromisoformat(manifest["created_at"])
    require(0 <= age.total_seconds() < 86400, "Backup gate expired; take a fresh backup")
    for name in ["postgres_backup", "sqlite_backup"]:
        file = Path(manifest[name]["path"]).resolve()
        require(
            file.is_relative_to(directory)
            and file.stat().st_size > 0
            and sha_file(file) == manifest[name]["sha256"],
            f"Backup hash mismatch: {name}",
        )
    require(
        sha_file(directory / "private-document-manifest.json")
        == manifest["document_manifest_sha256"],
        "Document manifest hash mismatch",
    )
    documents = json.loads((directory / "private-document-manifest.json").read_text())
    for document in documents:
        record = document["record"]
        physical = record["physical_file"]
        if physical["exists"]:
            key = record.get("storage_path") or record.get("pdf_key") or record.get("storage_key")
            root = Path(physical["source_root"]).resolve()
            file = root / key
            require(
                file.resolve().is_relative_to(root)
                and not file.is_symlink()
                and file.stat().st_size == physical["size"]
                and sha_file(file) == physical["sha256"],
                "Document changed since backup",
            )
    return manifest, documents


def target_rows(conn, table):
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            sql.SQL("SELECT * FROM {}.{} ORDER BY id").format(
                sql.Identifier(SCHEMA), sql.Identifier(table)
            )
        ).fetchall()


def verify_rows(conn, rows, views):
    actual_tables = {
        r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s", (SCHEMA,))
    }
    require(
        actual_tables
        == set(rows) | {"migration_versions", "source_identity_map", "document_manifest"},
        "Staging table inventory drift",
    )
    contract = json.loads(CONTRACT.read_text())
    counts = {}
    for table, records in rows.items():
        columns = conn.execute(
            """SELECT column_name,data_type,is_nullable
            FROM information_schema.columns WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position""",
            (SCHEMA, table),
        ).fetchall()
        expected_columns = []
        for column in contract["tables"][table]["columns"]:
            kind = {"TEXT": "text", "INTEGER": "bigint", "REAL": "double precision"}[column["type"]]
            if column["name"] in SALARIES:
                kind = "numeric"
            nullable = "NO" if column["notnull"] or column["pk"] else "YES"
            expected_columns.append((column["name"], kind, nullable))
        require(columns == expected_columns, f"Staging column contract drift: {table}")
        actual = target_rows(conn, table)
        require(
            {str(r["id"]): row_sha(r) for r in records}
            == {str(r["id"]): row_sha(r) for r in actual},
            f"Field/checksum reconciliation failure: {table}",
        )
        counts[table] = len(actual)
    for name, records in views.items():
        with conn.cursor(row_factory=dict_row) as cur:
            actual = cur.execute(
                sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(SCHEMA), sql.Identifier(name))
            ).fetchall()
        require(
            sorted(row_sha(r) for r in records) == sorted(row_sha(r) for r in actual),
            f"View reconciliation failure: {name}",
        )
    invalid = conn.execute(
        """SELECT count(*) FROM pg_constraint c JOIN pg_namespace n
        ON n.oid=c.connamespace WHERE n.nspname=%s AND NOT c.convalidated""",
        (SCHEMA,),
    ).fetchone()[0]
    require(invalid == 0, "Unvalidated staging constraints")
    return counts


def identity_records(rows, classifications):
    identities = []
    for table, records in rows.items():
        for row in records:
            kind, evidence = classifications[(table, str(row["id"]))]
            origin = row.get("legacy_source_table")
            if row.get("legacy_postgres_id") and table in {"candidates", "companies"}:
                origin = table
            identities.append(
                (
                    SOURCE_STORE_ID,
                    table,
                    str(row["id"]),
                    origin,
                    row.get("legacy_postgres_id"),
                    row_sha(row),
                    row_sha(row),
                    kind,
                    evidence,
                )
            )
            if table == "companies":
                for contact in json.loads(row["contacts_json"]):
                    identities.append(
                        (
                            SOURCE_STORE_ID,
                            "company_contacts_embedded",
                            f"{row['id']}/{contact['id']}",
                            "company_contacts" if kind == "IMPORTED_LEGACY" else None,
                            contact["id"] if kind == "IMPORTED_LEGACY" else None,
                            row_sha(contact),
                            row_sha(contact),
                            kind,
                            "Embedded contact; parent company classification and legacy identity",
                        )
                    )
    return sorted(identities, key=lambda r: (r[1], r[2]))


def migrate(conn, rows, views, classifications, manifest, documents):
    """Caller controls a single transaction. Any conflict raises before commit."""
    require(
        conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS,
        "Explicit transaction required",
    )
    require(
        conn.execute("SELECT pg_try_advisory_xact_lock(1246576980, 12003)").fetchone()[0],
        "Another V12 staging importer is running",
    )
    require(public_fingerprint(conn) == manifest["public_before"], "Legacy public data drift")
    migration_hash, contract_hash = sha_file(MIGRATION), sha_file(CONTRACT)
    identities = identity_records(rows, classifications)
    expected_version = (
        "001",
        migration_hash,
        contract_hash,
        SOURCE_STORE_ID,
        manifest["sqlite_backup"]["sha256"],
        manifest["postgres_backup"]["sha256"],
        fingerprint_sha(manifest["public_before"]),
    )
    existing = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone()
    if existing:
        # Unknown schemas are never adopted, changed, reset or overwritten.
        version = conn.execute(
            sql.SQL(
                "SELECT version,migration_sha256,source_contract_sha256,"
                "source_store_id,sqlite_backup_sha256,postgres_backup_sha256,"
                "public_fingerprint_sha256 "
                "FROM {}.migration_versions"
            ).format(sql.Identifier(SCHEMA))
        ).fetchall()
        # Backup hashes record the original import evidence, not source identity.
        # A fresh verified backup with unchanged rows must still be a safe no-op.
        require(
            len(version) == 1 and version[0][:4] == expected_version[:4],
            "Existing schema manifest conflicts; no writes allowed",
        )
        counts = verify_rows(conn, rows, views)
        actual = conn.execute(
            sql.SQL(
                "SELECT source_store_id,table_name,source_pk,legacy_source_table,"
                "legacy_postgres_id,source_sha256,target_sha256,classification,"
                "classification_evidence "
                "FROM {}.source_identity_map ORDER BY table_name,source_pk"
            ).format(sql.Identifier(SCHEMA))
        ).fetchall()
        require(
            sorted(actual, key=lambda r: (r[1], r[2])) == identities,
            "Existing source identity map conflict",
        )
        actual_docs = dict(
            conn.execute(
                sql.SQL(
                    "SELECT source_table||'/'||source_pk,manifest_json FROM {}.document_manifest"
                ).format(sql.Identifier(SCHEMA))
            ).fetchall()
        )
        require(
            actual_docs
            == {
                d["table"] + "/" + str(d["record"]["id"]): json.dumps(d["record"], sort_keys=True)
                for d in documents
            },
            "Existing document manifest conflict",
        )
        return {"inserted": 0, "skipped": sum(counts.values()), "blocked": 0, "counts": counts}

    conn.execute(MIGRATION.read_text(), prepare=False)
    conn.execute(
        sql.SQL(
            "INSERT INTO {}.migration_versions(version,migration_sha256,"
            "source_contract_sha256,source_store_id,sqlite_backup_sha256,postgres_backup_sha256,"
            "public_fingerprint_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s)"
        ).format(sql.Identifier(SCHEMA)),
        expected_version,
    )
    for table, records in rows.items():
        if not records:
            continue
        columns = list(records[0])
        statement = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
            sql.Identifier(SCHEMA),
            sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, columns)),
            sql.SQL(",").join(sql.Placeholder() for _ in columns),
        )
        with conn.cursor() as cur:
            cur.executemany(statement, [tuple(r[c] for c in columns) for r in records])
    with conn.cursor() as cur:
        cur.executemany(
            sql.SQL(
                "INSERT INTO {}.source_identity_map VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            ).format(sql.Identifier(SCHEMA)),
            identities,
        )
        cur.executemany(
            sql.SQL("INSERT INTO {}.document_manifest VALUES (%s,%s,%s)").format(
                sql.Identifier(SCHEMA)
            ),
            [
                (d["table"], str(d["record"]["id"]), json.dumps(d["record"], sort_keys=True))
                for d in documents
            ],
        )
    counts = verify_rows(conn, rows, views)
    for table in [*rows, "migration_versions", "source_identity_map", "document_manifest"]:
        conn.execute(
            sql.SQL(
                "CREATE TRIGGER freeze_snapshot BEFORE INSERT OR UPDATE OR DELETE "
                "OR TRUNCATE ON {}.{} FOR EACH STATEMENT EXECUTE FUNCTION "
                "{}.reject_snapshot_mutation()"
            ).format(sql.Identifier(SCHEMA), sql.Identifier(table), sql.Identifier(SCHEMA))
        )
    require(public_fingerprint(conn) == manifest["public_before"], "Public changed during staging")
    return {"inserted": sum(counts.values()), "skipped": 0, "blocked": 0, "counts": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verified-backup", required=True, type=Path)
    parser.add_argument("--baseline-v2", required=True, type=Path)
    parser.add_argument("--trusted-office-lan", action="store_true")
    parser.add_argument(
        "--apply-staging",
        action="store_true",
        help="Required explicit opt-in; only jobmitra_v12_stage can be written",
    )
    args = parser.parse_args()
    require(args.apply_staging, "No writes without --apply-staging")
    manifest, documents = validate_backup_gate(args.verified_backup)
    rows, views = read_source(manifest["sqlite_backup"]["path"])
    classifications = classify(rows, args.baseline_v2)
    settings = Settings()  # Actual configured PostgreSQL, never auto-selected local settings.
    require(
        args.trusted_office_lan or settings.db_sslmode == "verify-full",
        "Use certificate-verified TLS or an explicitly confirmed trusted office LAN",
    )
    sslmode = "disable" if args.trusted_office_lan else settings.db_sslmode
    os.umask(0o077)
    with psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        sslmode=sslmode,
        connect_timeout=5,
        autocommit=True,
        options="-c timezone=UTC -c lock_timeout=5000 -c statement_timeout=30000",
    ) as conn:
        identity = conn.execute(
            "SELECT host(inet_server_addr()),inet_server_port(),"
            "current_database(),current_user,version()"
        ).fetchone()
        require(list(identity) == manifest["server"], "Backup/destination server identity mismatch")
        mapping = verify_legacy_identities(conn, rows)
        with conn.transaction():
            result = migrate(conn, rows, views, classifications, manifest, documents)
        after = public_fingerprint(conn)
        require(after == manifest["public_before"], "Post-commit public fingerprint changed")
        report = {
            **result,
            "schema": SCHEMA,
            "identity_mapping": mapping,
            "classification": dict(Counter(v[0] for v in classifications.values())),
            "source_identity_rows_including_contacts": len(identity_records(rows, classifications)),
            "all_13_tables_field_reconciled": True,
            "all_5_views_reconciled": True,
            "public_before": manifest["public_before"],
            "public_after": after,
            "public_unchanged": True,
            "backup_path": str(args.verified_backup),
            "source_store_id": str(SOURCE_STORE_ID),
        }
        report_file = args.verified_backup / (
            "staging-result-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
        )
        report_file.write_text(json.dumps(report, indent=2))
        print(
            json.dumps({k: v for k, v in report.items() if not k.startswith("public_")}, indent=2)
        )
        print("REPORT", report_file)


if __name__ == "__main__":
    try:
        main()
    except (MigrationConflict, psycopg.Error) as error:
        # PostgreSQL error details can contain private row data, so never print them.
        if isinstance(error, MigrationConflict):
            raise SystemExit(str(error)) from None
        # A lost connection during COMMIT can leave the outcome unknown. Never
        # claim rollback or retry automatically in that case.
        raise SystemExit(
            f"Staging stopped: PostgreSQL {type(error).__name__}; "
            "inspect the destination read-only before retrying"
        ) from None

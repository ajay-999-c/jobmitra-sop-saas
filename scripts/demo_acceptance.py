"""Explicitly approved persistent DEMO acceptance run. Never migrates or deletes.

Writes use the running application APIs. Direct database access is read-only.
Keep runtime/demo-acceptance/manifest.json: it is the idempotency/ownership journal.
An interrupted HTTP write is NOT retried automatically (outcome may be committed).
"""

import argparse
import fcntl
import hashlib
import io
import json
import os
import stat
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from jobmitra.core.config import Settings
from jobmitra.core.database import build_engine

RUN = "DEMO-20261021-ACCEPTANCE-01"
STATE = Path("runtime/demo-acceptance/manifest.json")
ROOT = Path("/Users/mac/Documents/jobmitra/private-documents")
TARGET = {"host": "192.168.1.51", "port": 5432, "database": "jobmitra_dev", "user": "jobmitra_app"}
REVISION = "0004_candidate_desk"
TABLES = (
    "alembic_version",
    "companies",
    "company_contacts",
    "staff_members",
    "job_requirements",
    "job_recruiters",
    "activities",
    "tasks",
    "work_domains",
    "work_subdomains",
    "candidates",
    "candidate_visits",
    "job_search_requests",
    "candidate_documents",
    "resume_parse_results",
)


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(row):
    return sha(json.dumps(row, sort_keys=True, ensure_ascii=False).encode())


def save_json(path, value):
    """Atomic, private journal writes, including a pending marker BEFORE HTTP writes."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def snapshot(engine):
    """Fresh connection, consistent read-only snapshot; no business data is printed."""
    with engine.connect() as conn:
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
        check(
            conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalars().all()
            == [REVISION],
            "Unexpected database revision; stop",
        )
        return {
            table: conn.exec_driver_sql(f'SELECT to_jsonb(t) FROM public."{table}" t')
            .scalars()
            .all()
            for table in TABLES
        }


def row_id(row):
    if "job_id" in row and "staff_id" in row and "id" not in row:
        return row["job_id"] + "|" + row["staff_id"]
    return str(row.get("id", row.get("version_num")))


def preserve_baseline(rows, backup):
    for table, baseline in backup["baseline"].items():
        current = {row_id(r): fingerprint(r) for r in rows[table]}
        check(
            all(current.get(identity) == hashed for identity, hashed in baseline["rows"].items()),
            f"Historical row changed or missing in {table}; stop, do not auto-correct",
        )


def sample_pdf(label):
    stream = f"BT /F1 12 Tf 40 750 Td ({label}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
        b"<< /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    for offset in offsets:
        data += f"{offset:010} 00000 n \n".encode()
    return data + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()


def sample_docx():
    output = io.BytesIO()
    parts = {
        "[Content_Types].xml": "<Types "
        'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": "<Relationships "
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{RUN} synthetic resume "
        "only</w:t></w:r></w:p></w:body></w:document>",
    }
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in parts.items():
            archive.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), content)
    return output.getvalue()


class Acceptance:
    def __init__(self, engine, state, backup, client):
        self.engine, self.state, self.backup, self.client = engine, state, backup, client
        self.checks = []

    def call(self, method, path, expected=200, **kwargs):
        response = self.client.request(method, path, **kwargs)
        check(
            response.status_code == expected,
            f"{method} {path}: expected HTTP {expected}, received {response.status_code}",
        )
        return response

    def write(self, key, method, path, expected=201, **kwargs):
        if key in self.state["actions"]:
            return self.state["actions"][key]["result"]
        check(
            not self.state.get("pending"),
            "Uncertain earlier write: inspect journal before resuming",
        )
        self.state["pending"] = {"key": key, "method": method, "path": path}
        save_json(STATE, self.state)
        result = self.call(method, path, expected, **kwargs).json()
        self.state["actions"][key] = {"method": method, "path": path, "result": result}
        self.state["pending"] = None
        save_json(STATE, self.state)
        return result

    def passed(self, label):
        self.checks.append(label)

    def seed(self):
        staff = [
            self.write(
                f"staff{i}", "POST", "/api/staff", json={"display_name": f"DEMO-Staff-{i:02}"}
            )
            for i in (1, 2)
        ]
        companies = [
            self.write(
                f"company{i}",
                "POST",
                "/api/companies",
                json={
                    "company_name": f"DEMO-Company-{i:02}",
                    "address_line": RUN + " synthetic address",
                    "city": "DEMO City",
                    "contacts": [
                        {
                            "contact_name": f"DEMO-Contact-{i:02}",
                            "designation": RUN,
                            "phone_numbers": [],
                        }
                    ],
                    "general_phone_numbers": [],
                },
            )
            for i in (1, 2)
        ]
        self.passed("Two DEMO companies/contacts and two dynamic staff created through APIs")
        domain = self.write("domain", "POST", "/api/domains", json={"name": "DEMO-Domain-01"})
        sub = self.write(
            "subdomain",
            "POST",
            "/api/subdomains",
            json={"name": "DEMO-Subdomain-01", "domain_id": domain["id"]},
        )
        due = self.state["follow_up_date"]
        jobs = [
            self.write(
                f"job{i}",
                "POST",
                "/api/jobs",
                json={
                    "company_id": company["id"],
                    "job_title": f"DEMO-JD-{i:02}",
                    "actor_staff_id": staff[0]["id"],
                    "raw_requirement": RUN + " synthetic vacancy only",
                    "status": "Active",
                    "vacancies": 2,
                    "required_skills": ["DEMO Python"],
                },
            )
            for i, company in enumerate(companies, 1)
        ]
        jid = jobs[0]["id"]

        def job_write(key, suffix, payload, method="PATCH", expected=200):
            fresh = self.call("GET", f"/api/jobs/{jid}").json()
            return self.write(
                key,
                method,
                f"/api/jobs/{jid}{suffix}",
                expected,
                json={"actor_staff_id": staff[0]["id"], "version": fresh["version"], **payload},
            )

        job_write("recruiters", "/recruiters", {"staff_ids": [s["id"] for s in staff]}, "PUT")
        job_write("skills", "", {"required_skills": ["DEMO Python", "DEMO PostgreSQL"]})
        job_write("target", "/target", {"target_date": due, "target_milestone": "SELECTION"})
        job_write("focus", "/work-focus", {"current_work_focus": "CANDIDATE_CONTACT"})
        task = job_write(
            "task",
            "/tasks",
            {
                "title": "DEMO follow-up task",
                "note": RUN,
                "assigned_staff_id": staff[1]["id"],
                "due_date": due,
            },
            "POST",
            201,
        )
        job_write("note", "/notes", {"note": RUN + " — synthetic acceptance history"}, "POST", 201)
        check(task["job_id"] == jid, "Wrong task JD")
        fresh_job = self.call("GET", f"/api/jobs/{jid}").json()
        check(
            len(fresh_job["recruiters"]) == 2
            and fresh_job["current_work_focus"] == "CANDIDATE_CONTACT"
            and fresh_job["target_completed_at"] is None
            and fresh_job["status"] == "Active",
            "Incorrect JD tracking state",
        )
        check(
            len(self.call("GET", f"/api/jobs/{jid}/activities").json()) >= 6, "Missing JD history"
        )
        self.passed(
            "JD company linkage, multiple recruiters, skills, target, Candidate "
            "Contact, task/history"
        )
        self.passed("Focus does not complete selection or change Active JD status")
        candidates = []
        for i, relocate in enumerate((True, False, None), 1):
            candidates.append(
                self.write(
                    f"candidate{i}",
                    "POST",
                    "/api/candidates",
                    json={
                        "full_name": f"DEMO-Candidate-{i:02}",
                        "mobile": f"00000000000{i}",
                        "email": f"demo-candidate-{i:02}@example.com",
                        "source": "Walk-in" if i == 1 else "Other",
                        "role_title": "DEMO Software Tester",
                        "domain_id": domain["id"],
                        "subdomain_id": sub["id"],
                        "qualification": "DEMO BSc",
                        "experience_months": 24,
                        "skills": ["DEMO Python", "DEMO SQL"],
                        "hometown": "DEMO Town",
                        "home_state": "Gujarat",
                        "ready_to_relocate": relocate,
                        "current_salary_amount": "25000.00",
                        "current_salary_period": "Monthly",
                        "expected_salary_amount": "360000.00",
                        "expected_salary_period": "Annual",
                        "current_salary_basis": "Gross",
                        "expected_salary_basis": "CTC",
                        "notice_period_text": RUN,
                        "recorded_by_staff_id": staff[0]["id"],
                    },
                )
            )
        cid = candidates[0]["id"]
        base = f"/api/candidates/{cid}"
        self.write(
            "candidate_edit",
            "PATCH",
            base,
            200,
            json={
                "version": candidates[0]["version"],
                "qualification": "DEMO BSc — manually verified",
            },
        )
        self.call("PATCH", base, 409, json={"version": 1, "qualification": "STALE DEMO"})
        matches = self.call("GET", "/api/candidates", params={"q": "demo-candidate"}).json()
        check(
            {c["id"] for c in candidates} <= {r["id"] for r in matches},
            "Candidate search missing DEMO rows",
        )
        duplicates = self.call(
            "GET", "/api/candidates/duplicates", params={"mobile": candidates[0]["mobile"]}
        ).json()
        check(
            any(d["id"] == cid for d in duplicates), "Duplicate lookup missing existing candidate"
        )
        self.call(
            "POST",
            "/api/candidates",
            409,
            json={
                "full_name": "DEMO duplicate rejected",
                "mobile": candidates[0]["mobile"],
                "source": "Other",
            },
        )
        self.passed(
            "Candidate registration, edit, stale-write rejection, search, duplicate "
            "warning without merging"
        )
        self.passed(
            "Email/mobile/qualification/skills/catalog/role/location/salaries and "
            "relocation true/false/NULL"
        )
        self.write(
            "visit",
            "POST",
            base + "/visits",
            json={
                "visited_at": self.state["started_at"],
                "purpose": "DEMO returning office visit",
                "note": RUN,
                "recorded_by_staff_id": staff[1]["id"],
            },
        )
        visits = self.call("GET", "/api/office-visits", params={"candidate_id": cid}).json()
        check(len(visits) == 2, "Expected automatic initial walk-in and returning visit")
        search = self.write(
            "search",
            "POST",
            base + "/job-search",
            json={
                "desired_role": "DEMO Software Tester",
                "assigned_staff_id": staff[0]["id"],
                "next_action": "DEMO review only; do not contact",
                "note": RUN,
                "follow_up_date": due,
            },
        )
        self.write(
            "search_edit",
            "PATCH",
            "/api/job-search-requests/" + search["id"],
            200,
            json={
                "version": search["version"],
                "status": "Interviewing",
                "assigned_staff_id": staff[1]["id"],
                "next_action": "DEMO internal follow-up only",
                "follow_up_date": due,
            },
        )
        self.passed(
            "Returning visit, job-search status update, staff reassignment and follow-up persist"
        )
        before_parse = self.call("GET", base).json()

        def upload(key, data, extension, candidate_id=cid, **params):
            record = self.write(
                key,
                "POST",
                f"/api/candidates/{candidate_id}/documents",
                content=data,
                params={"kind": "ORIGINAL_RESUME", "staff_id": staff[0]["id"], **params},
                headers={
                    "X-Document-Filename": f"{RUN}-{key}.{extension}",
                    "Content-Type": "application/octet-stream",
                },
            )
            check(record["sha256"] == sha(data), "Upload hash mismatch")
            downloaded = self.call(
                "GET", f"/candidates/{candidate_id}/documents/{record['id']}/download"
            )
            check(
                downloaded.content == data
                and downloaded.headers.get("cache-control") == "no-store",
                "Download bytes or private cache headers incorrect",
            )
            return record

        original1 = upload("original1", sample_pdf(RUN + " original v1"), "pdf")
        original2 = upload("original2", sample_docx(), "docx")
        modified1 = upload(
            "modified1",
            sample_pdf(RUN + " modified v1"),
            "pdf",
            kind="MODIFIED_RESUME",
            source_document_id=original1["id"],
            reviewed="true",
        )
        modified2 = upload(
            "modified2",
            sample_pdf(RUN + " modified v2"),
            "pdf",
            kind="MODIFIED_RESUME",
            source_document_id=original2["id"],
            reviewed="true",
        )
        upload(
            "candidate2_original",
            sample_pdf(RUN + " candidate2 original"),
            "pdf",
            candidate_id=candidates[1]["id"],
        )
        check(
            [d["version"] for d in (original1, original2, modified1, modified2)] == [1, 2, 1, 2],
            "Resume version sequence incorrect",
        )
        for provider, original in (("ChatGPT", original1), ("Claude", original2)):
            self.write(
                "parse_" + provider,
                "POST",
                base + "/resume-parses",
                json={
                    "document_id": original["id"],
                    "provider": provider,
                    "model_label": RUN + " no external AI",
                    "pasted_by_staff_id": staff[0]["id"],
                    "parsed_json": {
                        "demo_run": RUN,
                        "skills": ["DEMO unconfirmed suggestion"],
                        "source_original_version": original["version"],
                    },
                },
            )
        check(
            self.call("GET", base).json() == before_parse, "Parsed JSON changed candidate profile"
        )
        other = candidates[1]["id"]
        self.call("GET", f"/candidates/{other}/documents/{original1['id']}/download", 404)
        self.call(
            "POST",
            f"/api/candidates/{other}/resume-parses",
            422,
            json={
                "document_id": original1["id"],
                "provider": "Claude",
                "parsed_json": {"demo_run": RUN},
            },
        )
        self.call(
            "POST",
            f"/api/candidates/{other}/documents",
            422,
            content=sample_pdf(RUN),
            headers={"X-Document-Filename": RUN + "-rejected.pdf"},
            params={
                "kind": "MODIFIED_RESUME",
                "source_document_id": original1["id"],
                "reviewed": "true",
            },
        )
        self.passed(
            "PDF/DOCX originals and modified versions: exact bytes, hashes, lineage "
            "and version history"
        )
        self.passed(
            "ChatGPT/Claude JSON retained on distinct original versions; manual profile unchanged"
        )
        self.passed("Cross-candidate download, parse and modified-source associations rejected")
        self.state["api_checks"] = self.checks
        self.state["seed_complete"] = True
        save_json(STATE, self.state)

    def ownership(self, rows):
        """Only journaled IDs and service-created children of those exact DEMO parents."""
        owned = {table: set() for table in TABLES}
        mapping = {
            "staff1": "staff_members",
            "staff2": "staff_members",
            "company1": "companies",
            "company2": "companies",
            "job1": "job_requirements",
            "job2": "job_requirements",
            "domain": "work_domains",
            "subdomain": "work_subdomains",
            "task": "tasks",
            "search": "job_search_requests",
            "candidate1": "candidates",
            "candidate2": "candidates",
            "candidate3": "candidates",
            "original1": "candidate_documents",
            "original2": "candidate_documents",
            "modified1": "candidate_documents",
            "modified2": "candidate_documents",
            "candidate2_original": "candidate_documents",
            "parse_ChatGPT": "resume_parse_results",
            "parse_Claude": "resume_parse_results",
        }
        for key, table in mapping.items():
            if key in self.state["actions"]:
                owned[table].add(self.state["actions"][key]["result"]["id"])
        for table, parent, field in (
            ("company_contacts", "companies", "company_id"),
            ("candidate_visits", "candidates", "candidate_id"),
            ("activities", "job_requirements", "job_id"),
            ("job_recruiters", "job_requirements", "job_id"),
        ):
            owned[table] = {row_id(r) for r in rows[table] if r[field] in owned[parent]}
        return owned

    def verify(self):
        rows = snapshot(self.engine)
        preserve_baseline(rows, self.backup)
        owned = self.ownership(rows)
        if self.state.get("owned"):
            check(
                {t: sorted(ids) for t, ids in owned.items()} == self.state["owned"],
                "DEMO ownership changed after initial run; review new child records",
            )
        for table, ids in owned.items():
            current = {row_id(r) for r in rows[table]}
            check(
                ids <= current and not ids.intersection(self.backup["baseline"][table]["rows"]),
                f"Missing or historical ID in DEMO manifest: {table}",
            )
            check(
                current == ids | set(self.backup["baseline"][table]["rows"]),
                f"Unjournaled new rows in {table}; review without deleting anything",
            )
        persisted_checks = []
        if self.state.get("seed_complete"):
            for number in (1, 2, 3):
                original = self.state["actions"][f"candidate{number}"]["result"]
                fresh = self.call("GET", "/api/candidates/" + original["id"]).json()
                for field in (
                    "full_name",
                    "mobile",
                    "email",
                    "role_title",
                    "domain_id",
                    "subdomain_id",
                    "skills",
                    "hometown",
                    "home_state",
                    "ready_to_relocate",
                    "current_salary_amount",
                    "current_salary_period",
                    "current_salary_basis",
                    "expected_salary_amount",
                    "expected_salary_period",
                    "expected_salary_basis",
                ):
                    check(
                        fresh[field] == original[field], f"DEMO candidate {number}: {field} changed"
                    )
                expected_qualification = {
                    1: {"DEMO BSc — manually verified"},
                    2: {"DEMO BSc"},
                    3: {"DEMO BSc", "DEMO BSc — UI verified"},
                }[number]
                check(fresh["qualification"] in expected_qualification, "Qualification mismatch")
            for key in ("parse_ChatGPT", "parse_Claude"):
                expected = self.state["actions"][key]["result"]
                actual = next(r for r in rows["resume_parse_results"] if r["id"] == expected["id"])
                check(
                    all(
                        actual[field] == expected[field]
                        for field in ("document_id", "provider", "parsed_json", "model_label")
                    ),
                    "Preserved parse JSON/provider/original-version mismatch",
                )
            for key in ("original1", "original2", "modified1", "modified2", "candidate2_original"):
                expected = self.state["actions"][key]["result"]
                actual = next(r for r in rows["candidate_documents"] if r["id"] == expected["id"])
                check(
                    all(
                        actual[field] == expected[field]
                        for field in (
                            "candidate_id",
                            "kind",
                            "source_document_id",
                            "version",
                            "sha256",
                        )
                    ),
                    "Persisted document association/version mismatch",
                )
            persisted_checks.extend(
                [
                    "All three candidate field sets verified after fresh read",
                    "Parsed JSON contents/providers/original versions verified from PostgreSQL",
                    "Document candidate/source/version links verified from PostgreSQL",
                ]
            )
        files = []
        for doc in rows["candidate_documents"]:
            if doc["id"] not in owned["candidate_documents"]:
                continue
            path = ROOT / doc["storage_key"]
            check(path.parent == ROOT and not path.is_symlink(), "Unsafe storage path")
            data = path.read_bytes()
            check(
                sha(data) == doc["sha256"] and len(data) == doc["size_bytes"],
                "Stored file mismatch",
            )
            check(stat.S_IMODE(path.stat().st_mode) == 0o600, "Private file permissions incorrect")
            download = self.call(
                "GET", f"/candidates/{doc['candidate_id']}/documents/{doc['id']}/download"
            )
            check(download.content == data, "Fresh-session download differs from persistent file")
            files.append(
                {
                    "document_id": doc["id"],
                    "candidate_id": doc["candidate_id"],
                    "storage_key": doc["storage_key"],
                    "sha256": doc["sha256"],
                }
            )
        for name, digest in self.backup["storage_files"].items():
            check(sha((ROOT / name).read_bytes()) == digest, "Historical document changed")
        expected_files = set(self.backup["storage_files"]) | {f["storage_key"] for f in files}
        actual_files = {str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()}
        check(
            actual_files == expected_files, "Unjournaled file or missing file; manual review needed"
        )
        report = {
            "run": RUN,
            "verified_at": datetime.now(UTC).isoformat(),
            "revision": REVISION,
            "historical_rows_unchanged": True,
            "counts_before": {t: b["count"] for t, b in self.backup["baseline"].items()},
            "counts_after": {t: len(r) for t, r in rows.items()},
            "owned": {t: sorted(ids) for t, ids in owned.items()},
            "files": files,
            "api_checks": self.state.get("api_checks", []),
            "persisted_checks": persisted_checks,
            "seed_complete": self.state.get("seed_complete", False),
        }
        self.state["owned"] = report["owned"]
        self.state["files"] = files
        save_json(STATE, self.state)
        save_json(STATE.parent / "verification.json", report)
        return rows, report

    def cleanup_preview(self, rows, report):
        owned = {t: set(ids) for t, ids in report["owned"].items()}
        all_ids = set().union(*owned.values())
        blockers = []
        for table, records in rows.items():
            for record in records:
                if row_id(record) in owned[table]:
                    continue
                if any(
                    isinstance(v, str) and v in all_ids
                    for k, v in record.items()
                    if k.endswith("_id")
                ):
                    blockers.append({"table": table, "id": row_id(record)})
        order = [
            "resume_parse_results",
            "candidate_documents",
            "job_search_requests",
            "candidate_visits",
            "candidates",
            "work_subdomains",
            "work_domains",
            "activities",
            "tasks",
            "job_recruiters",
            "job_requirements",
            "company_contacts",
            "companies",
            "staff_members",
        ]
        preview = {
            "mode": "preview_only_no_deletion_implemented",
            "run": RUN,
            "blockers": blockers,
            "review_required": True,
            "deletion_order": [{"table": t, "ids": report["owned"][t]} for t in order],
            "document_order": (
                "Delete modified document rows before source originals; "
                "delete files only after DB commit"
            ),
            "files": report["files"],
            "historical_records_excluded": True,
        }
        save_json(STATE.parent / "cleanup-preview.json", preview)
        return preview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--apply", action="store_true", help="Commit this approved DEMO dataset via localhost:8000"
    )
    mode.add_argument(
        "--verify", action="store_true", help="Read-only database/API/file verification"
    )
    mode.add_argument(
        "--cleanup-preview",
        action="store_true",
        help="Only list owned IDs/files and external references",
    )
    parser.add_argument("--backup-manifest", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE.parent / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings = Settings()
        check(
            {
                "host": settings.db_host,
                "port": settings.db_port,
                "database": settings.db_name,
                "user": settings.db_user,
            }
            == TARGET,
            "Unexpected database settings",
        )
        check(
            settings.document_storage_root == ROOT and ROOT.is_dir() and not ROOT.is_symlink(),
            "Unexpected private storage root",
        )
        check(stat.S_IMODE(ROOT.stat().st_mode) == 0o700, "Private storage must be mode 0700")
        state = json.loads(STATE.read_text()) if STATE.exists() else None
        check(args.apply or state is not None, "No DEMO manifest available")
        backup_path = Path(state["backup_manifest"]) if state else args.backup_manifest
        check(backup_path is not None, "First application requires a verified backup manifest")
        backup = json.loads(backup_path.read_text())
        check(
            backup["target"] == TARGET and backup["revision"] == REVISION,
            "Backup target/revision mismatch",
        )
        check(
            sha(Path(backup["database_archive"]).read_bytes()) == backup["database_sha256"],
            "Database backup changed",
        )
        check(
            sha(Path(backup["document_archive"]).read_bytes()) == backup["document_archive_sha256"],
            "File backup changed",
        )
        engine = build_engine(settings)
        try:
            rows = snapshot(engine)
            preserve_baseline(rows, backup)
            if state is None:
                check(
                    all(len(rows[t]) == b["count"] for t, b in backup["baseline"].items()),
                    "Backup is stale; capture new baseline",
                )
                for table, field in (
                    ("companies", "company_name"),
                    ("staff_members", "display_name"),
                    ("job_requirements", "job_title"),
                    ("candidates", "full_name"),
                    ("work_domains", "name"),
                ):
                    check(
                        not any(r[field].startswith("DEMO-") for r in rows[table]),
                        "Existing DEMO labels need manual review",
                    )
                state = {
                    "run": RUN,
                    "backup_manifest": str(backup_path.resolve()),
                    "actions": {},
                    "started_at": datetime.now(UTC).isoformat(),
                    "follow_up_date": (datetime.now(UTC).date() + timedelta(days=7)).isoformat(),
                }
                save_json(STATE, state)
            check(
                state["run"] == RUN and not state.get("pending"),
                "Run mismatch or uncertain pending write; review journal",
            )
            with httpx.Client(
                base_url="http://127.0.0.1:8000",
                timeout=30,
                trust_env=False,
                headers={"X-Jobmitra-UI": "1"},
            ) as client:
                runner = Acceptance(engine, state, backup, client)
                company_ids = {r["id"] for r in runner.call("GET", "/api/companies").json()}
                check(
                    company_ids == {r["id"] for r in rows["companies"]},
                    "Running backend does not match configured database",
                )
                if args.apply:
                    runner.seed()
                rows, report = runner.verify()
                if args.cleanup_preview:
                    runner.cleanup_preview(rows, report)
                print(
                    json.dumps(
                        {
                            "run": RUN,
                            "seed_complete": report["seed_complete"],
                            "historical_rows_unchanged": True,
                            "api_checks": len(report["api_checks"]),
                            "files_verified": len(report["files"]),
                            "counts_after": report["counts_after"],
                            "manifest": str(STATE),
                            "mode": "apply"
                            if args.apply
                            else "cleanup-preview"
                            if args.cleanup_preview
                            else "verify",
                        }
                    )
                )
        finally:
            engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Raw database/HTTP exceptions can contain private parameters; never echo them.
        print(
            "DEMO acceptance stopped: "
            + (str(error) if isinstance(error, RuntimeError) else type(error).__name__),
            file=sys.stderr,
        )
        raise SystemExit(1) from None

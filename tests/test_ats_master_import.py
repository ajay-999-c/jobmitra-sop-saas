"""Synthetic, offline master-import rehearsals; no existing database is contacted."""

import copy
import hashlib
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from jobmitra.modules.ats_v2.database import (
    SCHEMA_V1_PATH,
    build_ats_engine,
    initialize,
    transaction,
    validate,
)
from jobmitra.modules.ats_v2.master_import import (
    ImportConflict,
    execute_import,
    local_state,
    plan_import,
    stable_integer,
)
from jobmitra.modules.ats_v2.master_source import fingerprint

STAMP = "2020-01-01T00:00:00Z"
COMPANY = "10000000-0000-0000-0000-000000000001"
CANDIDATE = "20000000-0000-0000-0000-000000000001"
DOCUMENT = "30000000-0000-0000-0000-000000000001"
RESUME = "40000000-0000-0000-0000-000000000001"
PARSE = "50000000-0000-0000-0000-000000000001"
PAYLOAD = b"%PDF-1.4 synthetic resume\n%%EOF"


def finalize(tables):
    tables = copy.deepcopy(tables)
    hashes = {name: fingerprint(rows) for name, rows in tables.items()}
    return {
        "format": 1,
        "transaction_read_only": True,
        "tables": tables,
        "counts": {name: len(rows) for name, rows in tables.items()},
        "table_fingerprints": hashes,
        "source_fingerprint": fingerprint(hashes),
    }


def source_snapshot(*, resumes=True):
    tables = {
        "companies": [
            {
                "id": COMPANY,
                "company_name": "Imported Synthetic Company",
                "company_name_key": "imported synthetic company",
                "general_phone_numbers": [],
                "source_register_ids": [],
                "created_at": STAMP,
                "updated_at": STAMP,
            }
        ],
        "company_contacts": [],
        "work_domains": [],
        "work_subdomains": [],
        "candidates": [
            {
                "id": CANDIDATE,
                "full_name": "Imported Synthetic Candidate",
                "mobile": "9876543210",
                "mobile_normalized": "9876543210",
                "email": "imported@example.test",
                "source": "Walk-in",
                "role_title": "Engineer",
                "skills": ["Python"],
                "preferred_locations": ["Pune"],
                "experience_months": 36,
                "current_salary_amount": "25000.25",
                "current_salary_period": "Monthly",
                "current_salary_basis": "Gross",
                "expected_salary_amount": "50000.25",
                "expected_salary_period": "Monthly",
                "expected_salary_basis": "CTC",
                "notice_period_text": "30 days",
                "created_at": STAMP,
                "updated_at": STAMP,
            }
        ],
        "candidate_documents": [],
        "candidate_resumes": [],
        "resume_parse_results": [],
    }
    if resumes:
        tables["candidate_documents"] = [
            {
                "id": DOCUMENT,
                "candidate_id": CANDIDATE,
                "kind": "ORIGINAL_RESUME",
                "original_filename": "synthetic-document.pdf",
                "storage_key": "a" * 32 + ".pdf",
                "content_type": "application/pdf",
                "size_bytes": len(PAYLOAD),
                "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
                "version": 1,
                "created_at": STAMP,
            }
        ]
        tables["candidate_resumes"] = [
            {
                "id": RESUME,
                "candidate_id": CANDIDATE,
                "original_filename": "synthetic-resume.pdf",
                "storage_key": "b" * 32 + ".pdf",
                "mime_type": "application/pdf",
                "file_size": len(PAYLOAD),
                "file_hash": hashlib.sha256(PAYLOAD).hexdigest(),
                "is_active": True,
                "uploaded_at": STAMP,
                "extracted_text": "Synthetic private body",
            }
        ]
        tables["resume_parse_results"] = [
            {
                "id": PARSE,
                "document_id": DOCUMENT,
                "created_at": STAMP,
                "parsed_json": {"skills": ["Python"], "private": "Synthetic parsed profile"},
            }
        ]
    return finalize(tables)


@pytest.fixture
def workspace(tmp_path):
    source_root = tmp_path / "legacy-files"
    storage_root = tmp_path / "ats-files"
    source_root.mkdir()
    storage_root.mkdir()
    (source_root / ("a" * 32 + ".pdf")).write_bytes(PAYLOAD)
    (source_root / ("b" * 32 + ".pdf")).write_bytes(PAYLOAD)
    engines = []

    def create(version=1):
        path = tmp_path / f"ats-{len(engines)}.sqlite3"
        if version == 1:
            with sqlite3.connect(path) as connection:
                connection.executescript(SCHEMA_V1_PATH.read_text())
                connection.execute("PRAGMA journal_mode=WAL")
        engine = build_ats_engine(path)
        if version == 2:
            initialize(engine)
        engines.append(engine)
        return engine

    yield create, source_root, storage_root, tmp_path / "backups"
    for engine in engines:
        engine.dispose()


def state(engine):
    with engine.connect() as connection:
        return local_state(connection)


def run_import(engine, source, workspace, **kwargs):
    _, source_root, storage_root, backups = workspace
    return execute_import(
        engine,
        source,
        backup_directory=backups,
        storage_root=storage_root,
        source_root=source_root,
        **kwargs,
    )


def seed_native_v1(engine, storage_root):
    native = storage_root / "originals/native.pdf"
    native.parent.mkdir()
    native.write_bytes(b"Synthetic native resume retained")
    with transaction(engine) as connection:
        connection.exec_driver_sql(
            "INSERT INTO candidates(id,candidate_code,full_name,phone_normalized) "
            "VALUES(7,'LOCAL-7','Native Synthetic Candidate','919876500001')"
        )
        connection.exec_driver_sql(
            "INSERT INTO job_descriptions(id,jd_code,company_id,title,target_date,status) "
            "VALUES(9,'LOCAL-JD',?,'Native Synthetic JD',?,'ACTIVE')",
            (COMPANY, (date.today() + timedelta(days=10)).isoformat()),
        )
        connection.exec_driver_sql(
            "INSERT INTO jd_candidates(id,job_id,candidate_id) VALUES(11,9,7)"
        )
        connection.exec_driver_sql(
            "INSERT INTO candidate_resumes(id,candidate_id,source_type,resume_kind,storage_path) "
            "VALUES(13,7,'UPLOADED','ORIGINAL','originals/native.pdf')"
        )
        connection.exec_driver_sql("UPDATE candidates SET skills_json='[\"SQL\"]' WHERE id=7")
    return native


def test_v1_import_preserves_native_records_and_wal_backup_including_existing_jd_uuid(workspace):
    create, _, storage_root, _ = workspace
    engine = create()
    native = seed_native_v1(engine, storage_root)
    before = state(engine)
    wal = Path(str(engine.url.database) + "-wal")
    assert wal.is_file() and wal.stat().st_size > 0
    source = source_snapshot()
    report = run_import(engine, source, workspace, source_verifier=lambda: source)
    assert report["status"] == "verified" and report["source_unchanged"]
    assert report["imported"] == {"companies": 1, "candidates": 1, "resumes": 3}
    assert report["copied_files"] == 2
    validate(engine)
    after = state(engine)
    for table, rows in before.items():
        current = {row["id"]: row for row in after[table]}
        for row in rows:
            assert all(current[row["id"]][key] == value for key, value in row.items())
    assert native.read_bytes() == b"Synthetic native resume retained"
    assert after["job_descriptions"][0]["company_id"] == after["companies"][0]["id"] == COMPANY
    imported = next(row for row in after["candidates"] if row["legacy_postgres_id"])
    assert imported["expected_salary_inr"] == 50000.25
    assert json.loads(imported["source_json"])["expected_salary_amount"] == "50000.25"
    with sqlite3.connect(report["backup"]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
        assert backup.execute("SELECT count(*) FROM candidates").fetchone()[0] == 1
        assert backup.execute("SELECT count(*) FROM recruitment_events").fetchone()[0] == len(
            before["recruitment_events"]
        )
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    history = [row for row in after["recruitment_events"] if row["candidate_id"] == imported["id"]]
    assert [row["event_type"] for row in history].count("CANDIDATE_IMPORTED") == 1
    assert not any(row["event_type"] == "CANDIDATE_CREATED" for row in history)
    assert "Synthetic private body" not in str(history)
    assert "Synthetic parsed profile" not in str(history)


def test_second_import_is_idempotent_with_no_new_events_files_or_backup(workspace):
    create, _, storage_root, backups = workspace
    engine = create()
    source = source_snapshot()
    run_import(engine, source, workspace)
    before = state(engine)
    files = {path: path.read_bytes() for path in storage_root.rglob("*") if path.is_file()}
    backup_files = list(backups.iterdir())
    report = run_import(engine, source, workspace)
    assert report["imported"] == {"companies": 0, "candidates": 0, "resumes": 0}
    assert report["backup"] is None and report["copied_files"] == 0
    assert report["already_imported"] == {"companies": 1, "candidates": 1, "resumes": 3}
    assert state(engine) == before
    assert {path: path.read_bytes() for path in storage_root.rglob("*") if path.is_file()} == files
    assert list(backups.iterdir()) == backup_files


@pytest.mark.parametrize(
    "conflict,expected",
    [
        ("company_pk", "company_primary_key_conflict"),
        ("company_name", "possible_duplicate_company_name"),
        ("candidate_pk", "candidate_primary_key_or_code_conflict"),
        ("candidate_identity", "possible_duplicate_candidate_identity"),
    ],
)
def test_local_conflicts_abort_without_backups_or_clobbering(workspace, conflict, expected):
    create, _, storage_root, backups = workspace
    engine = create(2)
    source = source_snapshot(resumes=False)
    with transaction(engine) as connection:
        if conflict.startswith("company"):
            connection.exec_driver_sql(
                "INSERT INTO companies(id,company_name,company_name_key) VALUES(?,?,?)",
                (
                    COMPANY if conflict == "company_pk" else str(uuid4()),
                    "Native Synthetic",
                    "imported synthetic company"
                    if conflict == "company_name"
                    else "native synthetic",
                ),
            )
        else:
            connection.exec_driver_sql(
                "INSERT INTO candidates(id,full_name,phone_normalized) VALUES(?,?,?)",
                (
                    stable_integer("candidates", CANDIDATE) if conflict == "candidate_pk" else 7,
                    "Native Synthetic",
                    "919876543210" if conflict == "candidate_identity" else None,
                ),
            )
    before = state(engine)
    plan = plan_import(source, before)
    assert expected in {issue["code"] for issue in plan["conflicts"]}
    with pytest.raises(ImportConflict, match="Unresolved import conflicts"):
        run_import(engine, source, workspace)
    assert state(engine) == before
    assert not backups.exists() and not list(storage_root.rglob("*.pdf"))


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("companies", "city", "Changed City"),
        ("candidates", "role_title", "Changed Role"),
        ("candidate_documents", "version", 2),
    ],
)
def test_changed_source_does_not_overwrite_previously_imported_records(
    workspace, table, field, value
):
    create, _, storage_root, backups = workspace
    engine = create()
    source = source_snapshot()
    run_import(engine, source, workspace)
    before, files, backup_files = (
        state(engine),
        list(storage_root.rglob("*.pdf")),
        list(backups.iterdir()),
    )
    changed = copy.deepcopy(source["tables"])
    changed[table][0][field] = value
    with pytest.raises(ImportConflict, match="Unresolved import conflicts"):
        run_import(engine, finalize(changed), workspace)
    assert state(engine) == before
    assert list(storage_root.rglob("*.pdf")) == files
    assert list(backups.iterdir()) == backup_files


@pytest.mark.parametrize("condition", ["missing", "hash_mismatch"])
def test_missing_or_unverified_files_preserve_metadata_without_fabricating_download(
    workspace, condition
):
    create, source_root, storage_root, _ = workspace
    engine = create()
    source = source_snapshot()
    path = source_root / ("a" * 32 + ".pdf")
    if condition == "missing":
        path.unlink()
    else:
        path.write_bytes(b"Changed bytes")
    report = run_import(engine, source, workspace)
    assert report["copied_files"] == 1
    assert report["resume_file_plan"][condition] == 1
    record = next(
        row
        for row in state(engine)["candidate_resumes"]
        if row["legacy_source_table"] == "candidate_documents"
    )
    assert record["storage_path"] is None and record["is_current"] == 0
    assert json.loads(record["parsed_json"])["migration_file_status"] == condition
    assert json.loads(record["source_json"])["storage_key"] == "a" * 32 + ".pdf"
    assert len(list(storage_root.rglob("*.pdf"))) == 1


def test_source_change_after_copy_rolls_back_schema_rows_and_new_files(workspace):
    create, _, storage_root, backups = workspace
    engine = create()
    source = source_snapshot()
    before = state(engine)
    changed = copy.deepcopy(source)
    changed["source_fingerprint"] = "different-source"
    with pytest.raises(ImportConflict, match="source changed during import"):
        run_import(engine, source, workspace, source_verifier=lambda: changed)
    validate(engine, allow_v1=True)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == 1
    assert state(engine) == before
    assert not list(storage_root.rglob("*.pdf"))
    assert len(list(backups.glob("*.sqlite3"))) == 1


def test_unregistered_destination_file_is_never_overwritten(workspace):
    create, _, storage_root, _ = workspace
    engine = create()
    source = source_snapshot()
    existing = storage_root / f"imports/candidate_documents/{DOCUMENT}.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"Preserve this unrelated file")
    before = state(engine)
    with pytest.raises(ImportConflict, match="no file was overwritten"):
        run_import(engine, source, workspace)
    assert existing.read_bytes() == b"Preserve this unrelated file"
    assert state(engine) == before
    assert list(storage_root.rglob("*.pdf")) == [existing]


@pytest.mark.parametrize(
    "companies,candidates,expected",
    [
        (True, False, {"companies": 1, "candidates": 0, "resumes": 0}),
        (False, True, {"companies": 0, "candidates": 1, "resumes": 3}),
    ],
)
def test_explicit_partial_import_modes_do_not_import_unselected_masters(
    workspace, companies, candidates, expected
):
    create, _, _, _ = workspace
    engine = create()
    source = source_snapshot()
    report = run_import(engine, source, workspace, companies=companies, candidates=candidates)
    assert report["imported"] == expected
    actual = state(engine)
    assert len(actual["companies"]) == expected["companies"]
    assert len(actual["candidates"]) == expected["candidates"]
    assert len(actual["candidate_resumes"]) == expected["resumes"]

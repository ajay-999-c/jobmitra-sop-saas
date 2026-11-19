"""Explicit V1 -> V2 upgrades preserve live records and compose with imports atomically."""

import hashlib
import json
import sqlite3
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from jobmitra.modules.ats_v2.database import (
    CORE_TABLES,
    SCHEMA_V1_PATH,
    build_ats_engine,
    initialize,
    transaction,
    upgrade,
    validate,
)


@pytest.fixture
def version_one(tmp_path):
    path = tmp_path / "prior-ats.sqlite3"
    company_id = str(uuid4())
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA_V1_PATH.read_text())
        connection.execute(
            "INSERT INTO candidates(id,full_name,skills_json) VALUES(7,'Synthetic Existing','[]')"
        )
        connection.execute(
            "INSERT INTO job_descriptions(id,jd_code,company_id,title,target_date,status) "
            "VALUES(9,'JD-EXISTING',?,'Existing Synthetic JD',?,'ACTIVE')",
            (company_id, (date.today() + timedelta(days=10)).isoformat()),
        )
        connection.execute("INSERT INTO jd_candidates(id,job_id,candidate_id) VALUES(11,9,7)")
        connection.execute(
            "INSERT INTO candidate_resumes(candidate_id,source_type,resume_kind,storage_path) "
            "VALUES(7,'UPLOADED','ORIGINAL','originals/preserved.pdf')"
        )
        connection.execute("UPDATE candidates SET skills_json='[\"Python\"]' WHERE id=7")
    engine = build_ats_engine(path)
    try:
        yield engine, path, company_id
    finally:
        engine.dispose()


def snapshot(engine):
    with engine.connect() as connection:
        return {
            table: [tuple(row) for row in connection.exec_driver_sql(f"SELECT * FROM {table}")]
            for table in CORE_TABLES - {"companies"}
        }


def test_runtime_and_initializer_require_explicit_upgrade_without_changing_v1(version_one):
    engine, path, _ = version_one
    validate(engine, allow_v1=True)
    engine.dispose()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    for action in (validate, initialize):
        with pytest.raises(RuntimeError, match="explicit reviewed upgrade"):
            action(engine)
    engine.dispose()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_explicit_upgrade_keeps_prior_rows_ids_and_events_and_is_idempotent(version_one):
    engine, _, company_id = version_one
    prior = snapshot(engine)
    upgrade(engine)
    validate(engine)
    current = snapshot(engine)
    for table, rows in prior.items():
        # Provenance columns are appended; existing source values remain unchanged.
        assert (
            [row[: len(rows[0])] for row in current[table]] == rows if rows else not current[table]
        )
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == 2
        assert (
            connection.exec_driver_sql("SELECT company_id FROM job_descriptions").scalar_one()
            == company_id
        )
        assert connection.exec_driver_sql("SELECT count(*) FROM companies").scalar_one() == 0
    before = snapshot(engine)
    upgrade(engine)
    assert snapshot(engine) == before


def test_upgrade_composes_with_import_and_complete_rollback_restores_v1(version_one):
    engine, _, company_id = version_one
    before = snapshot(engine)
    with pytest.raises(RuntimeError, match="synthetic import failure"):
        with transaction(engine) as connection:
            upgrade(connection)
            connection.exec_driver_sql(
                "INSERT INTO companies(id,company_name,company_name_key) VALUES(?,?,'synthetic')",
                (company_id, "Imported Synthetic Company"),
            )
            raise RuntimeError("synthetic import failure")
    validate(engine, allow_v1=True)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == 1
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE name='companies'"
            ).scalar_one()
            == 0
        )
    assert snapshot(engine) == before


def test_upgrade_establishes_real_dbapi_transaction_when_sqlalchemy_has_not_begun(version_one):
    engine, _, _ = version_one
    with pytest.raises(RuntimeError, match="rollback"):
        with engine.begin() as connection:
            upgrade(connection)
            raise RuntimeError("rollback")
    validate(engine, allow_v1=True)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == 1


def test_fresh_and_upgraded_schema_match_and_company_references_are_guarded(version_one, tmp_path):
    engine, _, company_id = version_one
    upgrade(engine)
    fresh = build_ats_engine(tmp_path / "fresh.sqlite3")
    try:
        initialize(fresh)
        with engine.connect() as upgraded, fresh.connect() as empty:
            sql = "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
            assert list(upgraded.exec_driver_sql(sql)) == list(empty.exec_driver_sql(sql))
        with transaction(engine) as connection:
            connection.exec_driver_sql(
                "INSERT INTO companies(id,legacy_postgres_id,company_name,company_name_key) "
                "VALUES(?,?,?,'synthetic imported')",
                (company_id, company_id, "Synthetic Imported"),
            )
        with pytest.raises(IntegrityError), transaction(engine) as connection:
            connection.exec_driver_sql(
                "UPDATE job_descriptions SET company_id=? WHERE id=9", (str(uuid4()),)
            )
        with pytest.raises(IntegrityError), transaction(engine) as connection:
            connection.exec_driver_sql("DELETE FROM companies WHERE id=?", (company_id,))
        with transaction(engine) as connection:
            connection.exec_driver_sql("UPDATE companies SET is_active=0 WHERE id=?", (company_id,))
            # Historic JDs remain readable; inactive companies cannot receive new JDs.
        with pytest.raises(IntegrityError), transaction(engine) as connection:
            connection.exec_driver_sql(
                "INSERT INTO job_descriptions(jd_code,company_id,title,target_date) "
                "VALUES('NEW',?,'Synthetic',?)",
                (company_id, (date.today() + timedelta(days=1)).isoformat()),
            )
    finally:
        fresh.dispose()


def test_import_events_identify_provenance_without_fabricating_registration_or_resume_body(
    tmp_path,
):
    engine = build_ats_engine(tmp_path / "import.sqlite3")
    initialize(engine)
    candidate_source_id, resume_source_id = str(uuid4()), str(uuid4())
    try:
        with transaction(engine) as connection:
            imported_id = connection.exec_driver_sql(
                "INSERT INTO candidates(full_name,created_at,legacy_postgres_id,source_json,"
                "source_fingerprint,imported_at) VALUES('Imported Synthetic',"
                "'2020-01-01T00:00:00Z',?,?,?,'2026-11-17T00:00:00Z') RETURNING id",
                (
                    candidate_source_id,
                    '{"private":"synthetic source data"}',
                    "synthetic-fingerprint",
                ),
            ).scalar_one()
            connection.exec_driver_sql(
                "INSERT INTO candidate_resumes(candidate_id,source_type,resume_kind,raw_text,"
                "parsed_json,created_at,legacy_source_table,legacy_postgres_id,imported_at) "
                "VALUES(?,'UPLOADED','ORIGINAL','synthetic private resume',"
                "'{\"private\":\"synthetic parsed text\"}','2021-01-01T00:00:00Z',"
                "'candidate_resumes',?,'2026-11-17T00:00:00Z')",
                (imported_id, resume_source_id),
            )
            connection.exec_driver_sql(
                "INSERT INTO candidates(full_name) VALUES('Native Synthetic')"
            )
        with engine.connect() as connection:
            events = list(
                connection.exec_driver_sql(
                    "SELECT event_type,payload_json,created_at,after_json "
                    "FROM recruitment_events ORDER BY id"
                )
            )
        assert [row[0] for row in events] == [
            "CANDIDATE_IMPORTED",
            "RESUME_IMPORTED",
            "CANDIDATE_CREATED",
        ]
        provenance = json.loads(events[0][1])
        assert provenance["source_id"] == candidate_source_id
        assert provenance["source_created_at"] == "2020-01-01T00:00:00Z"
        assert provenance["source"] == "postgresql"
        assert events[0][2] != provenance["source_created_at"]
        assert "synthetic private resume" not in str(events)
        assert "synthetic parsed text" not in str(events)
        assert "synthetic source data" not in str(events)
        with pytest.raises(IntegrityError), transaction(engine) as connection:
            connection.exec_driver_sql(
                "INSERT INTO candidates(full_name,legacy_postgres_id) VALUES('Duplicate',?)",
                (candidate_source_id,),
            )
        with pytest.raises(IntegrityError), transaction(engine) as connection:
            connection.exec_driver_sql(
                "UPDATE candidates SET legacy_postgres_id=? WHERE id=?", (str(uuid4()), imported_id)
            )
    finally:
        engine.dispose()


def test_upgrade_rejects_unknown_or_drifted_databases_without_claiming_them(tmp_path):
    path = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated(synthetic TEXT)")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    engine = build_ats_engine(path)
    try:
        with pytest.raises(RuntimeError, match="Unsupported"):
            upgrade(engine)
    finally:
        engine.dispose()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

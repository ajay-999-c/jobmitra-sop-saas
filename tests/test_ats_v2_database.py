"""Isolated SQLite contracts for the additive ATS V2 schema and initializer."""

import hashlib
import json
import sqlite3
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from jobmitra.modules.ats_v2.database import (
    CORE_TABLES,
    build_ats_engine,
    initialize,
    transaction,
    validate,
)


@pytest.fixture
def ats_engine(tmp_path):
    engine = build_ats_engine(tmp_path / "isolated.sqlite3")
    initialize(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def add_job(connection, title="Synthetic JD"):
    company_id = str(uuid4())
    connection.exec_driver_sql(
        "INSERT INTO companies(id,company_name,company_name_key) VALUES(?,?,?)",
        (company_id, "Synthetic Company", "synthetic " + company_id),
    )
    return connection.exec_driver_sql(
        "INSERT INTO job_descriptions(jd_code,company_id,title,target_date,status) "
        "VALUES(?,?,?,?,'ACTIVE') RETURNING id",
        (str(uuid4()), company_id, title, (date.today() + timedelta(days=10)).isoformat()),
    ).scalar_one()


def add_candidate(connection):
    return connection.exec_driver_sql(
        "INSERT INTO candidates(full_name,skills_json) VALUES('Synthetic Candidate','[]') "
        "RETURNING id"
    ).scalar_one()


def test_eight_tables_uuid_reference_and_pragmas_on_each_connection(ats_engine):
    for _ in range(2):
        with ats_engine.connect() as connection:
            tables = set(
                connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).scalars()
            )
            assert tables == CORE_TABLES
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA recursive_triggers").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            company = next(
                row
                for row in connection.exec_driver_sql("PRAGMA table_info(job_descriptions)")
                if row[1] == "company_id"
            )
            assert company[2] == "TEXT"
            assert not list(connection.exec_driver_sql("PRAGMA foreign_key_list(job_descriptions)"))
        ats_engine.dispose()


def test_initializer_is_idempotent_and_validate_does_not_create_schema(ats_engine, tmp_path):
    with transaction(ats_engine) as connection:
        candidate_id = add_candidate(connection)
    initialize(ats_engine)
    validate(ats_engine)
    with ats_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT id FROM candidates").scalar_one() == candidate_id
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM recruitment_events").scalar_one() == 1
        )
    empty = build_ats_engine(tmp_path / "empty.sqlite3")
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            validate(empty)
        with empty.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT count(*) FROM sqlite_master").scalar_one() == 0
            )
    finally:
        empty.dispose()


@pytest.mark.parametrize("source", ["unrelated", "reference_v31"])
def test_existing_unknown_databases_are_refused_without_changes(tmp_path, source):
    path = tmp_path / f"{source}.sqlite3"
    with sqlite3.connect(path) as connection:
        if source == "reference_v31":
            connection.executescript(
                "CREATE TABLE companies(id INTEGER PRIMARY KEY,company_name TEXT); "
                "PRAGMA user_version=31;"
            )
        else:
            connection.executescript(
                "CREATE TABLE private_notes(body TEXT); "
                "INSERT INTO private_notes VALUES('synthetic');"
            )
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    engine = build_ats_engine(path)
    try:
        with pytest.raises(RuntimeError, match="Unsupported"):
            initialize(engine)
    finally:
        engine.dispose()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_partial_or_modified_schema_is_not_silently_repaired(ats_engine):
    with transaction(ats_engine) as connection:
        connection.exec_driver_sql("DROP TRIGGER trg_events_block_delete")
    with pytest.raises(RuntimeError, match="schema differs"):
        initialize(ats_engine)
    with ats_engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE name='trg_events_block_delete'"
            ).scalar_one()
            == 0
        )


def test_candidate_audit_tracks_changed_fields_and_resume_events_exclude_bodies(ats_engine):
    with transaction(ats_engine) as connection:
        candidate = add_candidate(connection)
        connection.exec_driver_sql(
            "UPDATE candidates SET skills_json=?,expected_salary_inr=42000 WHERE id=?",
            ('["Python", "SQL"]', candidate),
        )
        connection.exec_driver_sql(
            "INSERT INTO candidate_resumes(candidate_id,source_type,resume_kind,"
            "raw_text,parsed_json) VALUES(?,'UPLOADED','ORIGINAL',?,?)",
            (candidate, "synthetic private text", '{"private":"synthetic profile"}'),
        )
    with ats_engine.connect() as connection:
        events = (
            connection.exec_driver_sql("SELECT * FROM recruitment_events ORDER BY id")
            .mappings()
            .all()
        )
        assert [e["event_type"] for e in events] == [
            "CANDIDATE_CREATED",
            "CANDIDATE_UPDATED",
            "RESUME_ADDED",
        ]
        assert json.loads(events[1]["before_json"]) == {
            "skills_json": [],
            "expected_salary_inr": None,
        }
        assert json.loads(events[1]["after_json"]) == {
            "skills_json": ["Python", "SQL"],
            "expected_salary_inr": 42000,
        }
        assert "synthetic private text" not in str(events[-1])
        assert "synthetic profile" not in str(events[-1])
        assert events[-1]["created_at"].endswith("Z")
    for statement in [
        "UPDATE recruitment_events SET event_type='changed'",
        "DELETE FROM recruitment_events",
    ]:
        with pytest.raises(IntegrityError), transaction(ats_engine) as connection:
            connection.exec_driver_sql(statement)


def test_resume_versions_are_immutable_and_atomic_rollback_preserves_prior(ats_engine):
    with transaction(ats_engine) as connection:
        candidate = add_candidate(connection)
        resume_id = connection.exec_driver_sql(
            "INSERT INTO candidate_resumes(candidate_id,source_type,resume_kind,storage_path) "
            "VALUES(?,'UPLOADED','ORIGINAL','originals/synthetic-v1.pdf') RETURNING id",
            (candidate,),
        ).scalar_one()
    with pytest.raises(IntegrityError), transaction(ats_engine) as connection:
        connection.exec_driver_sql(
            "UPDATE candidate_resumes SET is_current=0 WHERE id=?", (resume_id,)
        )
        connection.exec_driver_sql(
            "INSERT INTO candidate_resumes(candidate_id,source_type,resume_kind,storage_path) "
            "VALUES(999999,'UPLOADED','ORIGINAL','originals/invalid.pdf')"
        )
    with ats_engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT is_current FROM candidate_resumes WHERE id=?", (resume_id,)
            ).scalar_one()
            == 1
        )
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM candidate_resumes").scalar_one() == 1
        )
    with pytest.raises(IntegrityError), transaction(ats_engine) as connection:
        connection.exec_driver_sql(
            "UPDATE candidate_resumes SET storage_path='overwrite.pdf' WHERE id=?", (resume_id,)
        )


def test_round_rename_and_rejection_preserve_event_labels_and_integrity(ats_engine):
    with transaction(ats_engine) as connection:
        candidate, job = add_candidate(connection), add_job(connection)
        round_id = str(uuid4())
        connection.exec_driver_sql(
            "INSERT INTO jd_interview_rounds(id,job_id,round_name,display_order) VALUES(?,?,?,1)",
            (round_id, job, "Original Interview"),
        )
        link = connection.exec_driver_sql(
            "INSERT INTO jd_candidates(job_id,candidate_id) VALUES(?,?) RETURNING id",
            (job, candidate),
        ).scalar_one()
        connection.exec_driver_sql(
            "UPDATE jd_candidates SET stage_code='ROUND',round_id=? WHERE id=?", (round_id, link)
        )
        connection.exec_driver_sql(
            "UPDATE jd_interview_rounds SET round_name='Renamed Interview',"
            "display_order=2 WHERE id=?",
            (round_id,),
        )
        connection.exec_driver_sql(
            "UPDATE jd_candidates SET stage_code='NOT_SELECTED',round_id=NULL,"
            "rejected_from_stage='ROUND',rejected_round_name='Renamed Interview',"
            "rejected_round_index=2,rejected_at='2026-01-01T00:00:00Z' WHERE id=?",
            (link,),
        )
    with ats_engine.connect() as connection:
        moved = connection.exec_driver_sql(
            "SELECT to_label_snapshot FROM recruitment_events WHERE event_type='MOVED'"
        ).scalar_one()
        rejected = connection.exec_driver_sql(
            "SELECT from_label_snapshot,after_json FROM recruitment_events "
            "WHERE event_type='REJECTED'"
        ).one()
        assert moved == "Original Interview"
        assert rejected[0] == "Renamed Interview"
        assert json.loads(rejected[1])["rejected_round_name"] == "Renamed Interview"
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
        assert list(connection.exec_driver_sql("PRAGMA foreign_key_check")) == []
    with pytest.raises(IntegrityError), transaction(ats_engine) as connection:
        connection.exec_driver_sql("UPDATE jd_candidates SET stage_code='POOL' WHERE id=?", (link,))
    with pytest.raises(IntegrityError), transaction(ats_engine) as connection:
        connection.exec_driver_sql("DELETE FROM jd_interview_rounds WHERE id=?", (round_id,))

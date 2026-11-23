"""Opt-in tests against a disposable, Unix-socket-only PostgreSQL restore.

Never reads the live server configuration or accepts a TCP database endpoint.
"""

import copy
import importlib.util
import json
import os
from collections import Counter
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("v12_stage", ROOT / "scripts/stage_v12_postgres.py")
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


@pytest.fixture(scope="module")
def source():
    backup = os.environ.get("JOBMITRA_STAGE_TEST_BACKUP")
    if not backup:
        pytest.skip("Explicit verified backup and disposable restore required")
    manifest, documents = stage.validate_backup_gate(backup)
    rows, views = stage.read_source(manifest["sqlite_backup"]["path"])
    baseline = ROOT / r"D:\JobmitraData\private\ats-v2.sqlite3"
    classes = stage.classify(rows, baseline)
    return rows, views, classes, manifest, documents


@pytest.fixture
def pg(source):
    socket = Path(os.environ["JOBMITRA_STAGE_TEST_SOCKET"]).resolve()
    assert socket.parent.name.startswith("jobmitra-v12-restore-")
    assert str(socket).startswith("/private/tmp/") and socket.name == "socket"
    with psycopg.connect(
        host=str(socket), dbname="postgres", user="restore_owner", options="-c timezone=UTC"
    ) as conn:
        assert conn.execute("SELECT inet_server_addr(),current_user").fetchone() == (
            None,
            "restore_owner",
        )
        assert not conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname=%s", (stage.SCHEMA,)
        ).fetchone()
        try:
            yield conn
        finally:
            conn.rollback()  # Including every test-created schema and table.


def apply(pg, source):
    return stage.migrate(pg, *source)


def test_full_import_checksums_views_mapping_and_public_unchanged(pg, source):
    result = apply(pg, source)
    assert result["inserted"] == 664
    assert len(result["counts"]) == 13
    assert result["skipped"] == result["blocked"] == 0
    assert stage.public_fingerprint(pg) == source[3]["public_before"]
    assert stage.verify_legacy_identities(pg, source[0]) == {
        "candidates": 187,
        "companies": 136,
        "contacts": 110,
        "resumes": 17,
    }
    assert (
        pg.execute("SELECT count(*) FROM jobmitra_v12_stage.source_identity_map").fetchone()[0]
        == 779
    )
    assert (
        pg.execute("SELECT count(*) FROM jobmitra_v12_stage.document_manifest").fetchone()[0] == 25
    )
    assert Counter(v[0] for v in source[2].values()) == {
        "IMPORTED_LEGACY": 544,
        "DEVELOPMENT_TEST": 120,
    }


def test_repeat_with_fresh_backup_hash_is_noop(pg, source):
    apply(pg, source)
    retry = list(source)
    retry[3] = copy.deepcopy(source[3])
    retry[3]["postgres_backup"]["sha256"] = "a" * 64
    retry[3]["sqlite_backup"]["sha256"] = "b" * 64
    result = stage.migrate(pg, *retry)
    assert (result["inserted"], result["skipped"], result["blocked"]) == (0, 664, 0)


@pytest.mark.parametrize("field", ["full_name", "source_json", "current_salary_inr"])
def test_conflicting_retry_fails_without_overwrite(pg, source, field):
    apply(pg, source)
    changed = copy.deepcopy(source[0])
    row = next(r for r in changed["candidates"] if r["current_salary_inr"] is not None)
    if field == "source_json":
        row[field] = " " + row[field]
    elif field == "current_salary_inr":
        row[field] = Decimal(str(row[field])) + Decimal("0.01")
    else:
        row[field] += " changed"
    with pytest.raises(stage.MigrationConflict, match="checksum reconciliation"):
        stage.migrate(pg, changed, *source[1:])
    stage.verify_rows(pg, source[0], source[1])


def test_foreign_key_error_rolls_back_entire_schema(pg, source):
    changed = copy.deepcopy(source[0])
    changed["candidate_resumes"][0]["candidate_id"] = -999
    with pytest.raises(psycopg.errors.ForeignKeyViolation), pg.transaction():
        stage.migrate(pg, changed, *source[1:])
    assert not pg.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (stage.SCHEMA,)).fetchone()


def test_reconciliation_error_rolls_back_entire_schema(pg, source):
    wrong_views = copy.deepcopy(source[1])
    wrong_views["v_candidate_allocation_eligibility"][0]["allocation_eligibility"] = "INVALID"
    with pytest.raises(stage.MigrationConflict, match="View reconciliation"), pg.transaction():
        stage.migrate(pg, source[0], wrong_views, *source[2:])
    assert not pg.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (stage.SCHEMA,)).fetchone()


def test_concurrent_import_fails_closed(pg, source):
    pg.execute("SELECT pg_advisory_xact_lock(1246576980,12003)")
    with psycopg.connect(
        host=pg.info.host, dbname="postgres", user="restore_owner", options="-c timezone=UTC"
    ) as other:
        other.execute("SELECT 1")
        with pytest.raises(stage.MigrationConflict, match="Another V12 staging importer"):
            apply(other, source)
        other.rollback()


def test_unknown_existing_schema_is_not_overwritten(pg, source):
    pg.execute("CREATE SCHEMA jobmitra_v12_stage")
    pg.execute("CREATE TABLE jobmitra_v12_stage.unrelated (id bigint PRIMARY KEY)")
    pg.execute("INSERT INTO jobmitra_v12_stage.unrelated VALUES (42)")
    with pytest.raises(psycopg.errors.UndefinedTable), pg.transaction():
        apply(pg, source)
    assert pg.execute("SELECT id FROM jobmitra_v12_stage.unrelated").fetchone() == (42,)


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE jobmitra_v12_stage.candidates SET full_name=full_name",
        "DELETE FROM jobmitra_v12_stage.recruitment_events",
        "TRUNCATE jobmitra_v12_stage.candidate_activities",
        "INSERT INTO jobmitra_v12_stage.candidates(id,full_name) VALUES (-1,'blocked')",
    ],
)
def test_completed_snapshot_rejects_all_business_writes(pg, source, operation):
    apply(pg, source)
    with pytest.raises(psycopg.errors.RaiseException, match="Immutable V12"), pg.transaction():
        pg.execute(operation)
    stage.verify_rows(pg, source[0], source[1])


def test_all_foreign_keys_are_isolated_and_validated(pg, source):
    apply(pg, source)
    foreign_keys = pg.execute("""SELECT n2.nspname,c.convalidated FROM pg_constraint c
        JOIN pg_namespace n ON n.oid=c.connamespace
        JOIN pg_class t ON t.oid=c.confrelid JOIN pg_namespace n2 ON n2.oid=t.relnamespace
        WHERE n.nspname='jobmitra_v12_stage' AND c.contype='f'""").fetchall()
    assert len(foreign_keys) >= 18
    assert all(schema == stage.SCHEMA and valid for schema, valid in foreign_keys)
    assert (
        pg.execute("""SELECT count(*) FROM pg_namespace n,
        LATERAL aclexplode(n.nspacl) a WHERE n.nspname='jobmitra_v12_stage'
        AND a.grantee=0""").fetchone()[0]
        == 0
    )


def test_salary_precision_and_json_exact_bytes(pg, source):
    apply(pg, source)
    fractional = [
        r
        for r in source[0]["candidates"]
        if r["current_salary_inr"] is not None and Decimal(str(r["current_salary_inr"])) % 1
    ]
    assert len(fractional) == 4
    for row in fractional:
        actual = pg.execute(
            "SELECT current_salary_inr,source_json FROM jobmitra_v12_stage.candidates WHERE id=%s",
            (row["id"],),
        ).fetchone()
        assert actual[0] == Decimal(str(row["current_salary_inr"]))
        assert actual[1].encode() == row["source_json"].encode()


def test_public_drift_stops_before_schema_creation(pg, source):
    bad = copy.deepcopy(source[3])
    bad["public_before"]["candidates"]["sha256"] = "0" * 64
    with pytest.raises(stage.MigrationConflict, match="public data drift"):
        stage.migrate(pg, *source[:3], bad, source[4])
    assert not pg.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (stage.SCHEMA,)).fetchone()


def test_unreviewed_development_identity_is_blocked(source):
    changed = copy.deepcopy(source[0])
    next(r for r in changed["candidates"] if not r["legacy_postgres_id"])["full_name"] = "Unknown"
    with pytest.raises(stage.MigrationConflict, match="Unreviewed unmapped candidate"):
        stage.classify(changed, ROOT / r"D:\JobmitraData\private\ats-v2.sqlite3")


def test_backup_tamper_fails_closed(source, tmp_path, monkeypatch):
    # No private documents are copied into the repository test directory.
    manifest = copy.deepcopy(source[3])
    manifest["verified"] = False
    (tmp_path / "backup-verification.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(stage, "ROOT", ROOT)
    with pytest.raises(stage.MigrationConflict, match="restore gate"):
        stage.validate_backup_gate(tmp_path)

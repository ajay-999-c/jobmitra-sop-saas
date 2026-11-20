"""Focused registration filters, purpose and lossless development source extension."""

import json
import sqlite3
from datetime import UTC, datetime
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_unified_v12 import HEADERS, OPERATOR
from test_unified_v12 import store as store
from test_unified_v12 import v2 as v2

from jobmitra.core import config
from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import candidate_registers as registers
from jobmitra.modules.ats_v2 import profile_store, registration_store
from jobmitra.modules.ats_v2.database import _objects, build_ats_engine, transaction, validate

NOW = datetime(2026, 11, 20, 8, tzinfo=UTC)


def snapshot(engine):
    with engine.connect() as c:
        return list(
            c.exec_driver_sql("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
        ), registration_store._rows(c)


@pytest.fixture
def prepared(store, monkeypatch):
    profile_store.install(store[0])
    root = store[-1] / "runtime"
    root.mkdir()
    path = root / "registers.sqlite3"
    with sqlite3.connect(store[-1] / "isolated.sqlite3") as old, sqlite3.connect(path) as new:
        old.backup(new)
    monkeypatch.setattr(config, "PROJECT_ENV_FILE", store[-1] / ".env")
    engine = build_ats_engine(path)
    yield engine, path, store[3]
    engine.dispose()


@pytest.fixture
def enabled(prepared):
    registration_store.install(prepared[0])
    return prepared


@pytest.fixture
def api(enabled):
    engine, path, cid = enabled
    settings = Settings(
        _env_file=None,
        db_host="127.0.0.1",
        db_port=9,
        db_name="unused",
        db_user="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=path,
        ats_v2_resume_storage_root=path.parent / "resumes",
        unified_v12_enabled=True,
        unified_v12_operator_token=OPERATOR,
    )
    with (
        patch("jobmitra.main.build_engine", return_value=Mock()),
        TestClient(create_app(settings)) as c,
    ):
        c.headers.update(HEADERS)
        assert c.post("/api/v12/access", json={"token": OPERATOR}).status_code == 200
        yield c, engine, cid


def seed(engine, name, stamp, source="WALK_IN", **extra):
    values = {
        "full_name": name,
        "created_at": stamp,
        "updated_at": stamp,
        "source": source,
        "candidate_code": str(uuid4()),
        **extra,
    }
    with transaction(engine) as c:
        return c.execute(
            text(
                "INSERT INTO candidates("
                + ",".join(values)
                + ") VALUES("
                + ",".join(":" + k for k in values)
                + ")"
            ),
            values,
        ).lastrowid


@pytest.fixture
def boundaries(enabled):
    engine = enabled[0]
    timestamps = [
        "2026-11-19T18:29:59.999Z",
        "2026-11-19T18:30:00Z",
        "2026-11-20T18:29:59.999Z",
        "2026-11-20T18:30:00Z",
        "2026-11-15T18:29:59.999Z",
        "2026-11-15T18:30:00Z",
        "2026-10-31T18:30:00Z",
        "2025-12-31T18:30:00Z",
        "2025-12-31T18:29:59.999Z",
    ]
    ids = [seed(engine, "Boundary " + str(i), stamp) for i, stamp in enumerate(timestamps)]
    email = seed(engine, "Email Boundary", "2026-11-19T18:30:00Z", "EMAIL")
    return engine, ids, email


@pytest.mark.parametrize(
    ("period", "count"),
    [("ALL", 9), ("TODAY", 2), ("WEEK", 5), ("MONTH", 7), ("YEAR", 8), ("CUSTOM", 3)],
)
def test_india_calendar_ranges_monday_week_and_source_combinations(boundaries, period, count):
    engine, _, email = boundaries
    args = {"period": period, "source": "WALK_IN"}
    if period == "CUSTOM":
        args.update(date_from="2026-11-19", date_to="2026-11-20")
    result = registers.dashboard(engine, registers.Filters(**args), NOW)
    assert result["new_candidates_selected_period"] == count
    assert result["total_candidates_all_time"] == 11
    assert len(result["recent"]) == min(5, count)
    assert (
        registers.dashboard(engine, registers.Filters(period="TODAY", source="EMAIL"), NOW)[
            "new_candidates_selected_period"
        ]
        == 1
    )
    if period == "WEEK":
        assert result["calendar"]["start_date"] == "2026-11-16"
    if period == "TODAY":
        assert result["calendar"]["start_utc"] == "2026-11-19T18:30:00+00:00"


def test_directory_search_fields_newest_first_pagination_and_literal_queries(enabled):
    engine = enabled[0]
    ids = []
    for i in range(27):
        ids.append(
            seed(
                engine,
                f"Directory Person {i:02}",
                f"2026-11-{i + 1:02}T01:00:00Z",
                phone=f"9800000{i:03}",
                phone_normalized=f"919800000{i:03}",
                email=f"directory-{i}@example.test",
                job_title="Directory Architect",
            )
        )
    for query in ["Person 05", "9800000005", "directory-5@example.test", "Architect"]:
        result = registers.directory(engine, registers.Directory(q=query))
        assert ids[5] in [r["id"] for r in result["items"]] or (
            query == "Architect" and result["total"] == 27
        )
    first = registers.directory(engine, registers.Directory(q="Directory", page_size=20))
    second = registers.directory(engine, registers.Directory(q="Directory", page=2, page_size=20))
    assert (
        first["total"] == second["total"] == 27
        and len(first["items"]) == 20
        and len(second["items"]) == 7
    )
    assert [r["id"] for r in first["items"] + second["items"]] == ids[::-1]
    assert registers.directory(engine, registers.Directory(q="%' OR 1=1 --"))["total"] == 0
    assert registers.directory(engine, registers.Directory(q="%", source="WALK_IN"))["total"] == 0


def test_directory_custom_inclusive_dates_source_and_api_validation(api):
    c, engine, _ = api
    cid = seed(engine, "Email Custom", "2026-11-20T18:29:59.999Z", "EMAIL")
    seed(engine, "After End", "2026-11-20T18:30:00Z", "EMAIL")
    params = {
        "period": "CUSTOM",
        "date_from": "2026-11-20",
        "date_to": "2026-11-20",
        "source": "EMAIL",
    }
    data = c.get("/api/v12/approved/candidate-directory", params=params).json()
    assert data["total"] == 1 and data["items"][0]["id"] == cid
    assert (
        c.get("/api/v12/approved/candidate-dashboard", params=params).json()[
            "new_candidates_selected_period"
        ]
        == 1
    )
    assert (
        c.get("/api/v12/approved/candidate-directory", params={"period": "CUSTOM"}).status_code
        == 422
    )
    assert (
        c.get("/api/v12/approved/candidate-directory", params={"source": "FAKE"}).status_code == 422
    )
    assert (
        c.get("/api/v12/approved/candidate-directory", params={"page_size": 101}).status_code == 422
    )
    assert {s["value"] for s in data["sources"]} == {
        "MANUAL",
        "WALK_IN",
        "FOUNDIT_PASTE",
        "RESUME_UPLOAD",
        "OTHER",
        "EMAIL",
    }


def register(c, purpose=None, source="EMAIL"):
    body = {
        "candidate": {
            "full_name": "Purpose " + uuid4().hex,
            "phone": "9899000001",
            "source": source,
        },
        "source_label": "Email",
        "registration_purpose": purpose,
    }
    return c.post(
        "/api/v12/approved/registration", json=body, headers={"Idempotency-Key": str(uuid4())}
    )


def test_registration_timestamp_optional_purpose_edit_and_original_evidence(api):
    c, engine, existing = api
    existing_before = c.get(f"/api/v12/approved/candidates/{existing}/profile").json()
    r = register(c, "Resume submission and career consultation")
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    path = f"/api/v12/approved/candidates/{cid}/profile"
    before = c.get(path).json()
    assert before["candidate"]["created_at"] and before["candidate"]["source"] == "EMAIL"
    assert before["extra"]["registration_purpose"] == "Resume submission and career consultation"
    for purpose in ["Follow-up", None]:
        response = c.patch(
            path,
            json={
                "changes": {},
                "extra": {"registration_purpose": purpose},
                "approved_fields": ["extra:registration_purpose"],
                "actor_name": "Synthetic reviewer",
                "expected_revision": before["revision"],
                "idempotency_key": str(uuid4()),
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200, response.text
        after = c.get(path).json()
        assert after["extra"]["registration_purpose"] == purpose
        assert after["candidate"]["created_at"] == before["candidate"]["created_at"]
        before = after
    with engine.connect() as conn:
        original = json.loads(
            conn.scalar(
                text(
                    "SELECT payload_json FROM recruitment_events WHERE candidate_id=:c "
                    "AND event_type='REGISTRATION_DETAILS'"
                ),
                {"c": cid},
            )
        )
        assert original["registration_purpose"] == "Resume submission and career consultation"
        assert conn.scalar(text("SELECT count(*) FROM candidate_activities")) == 0
    history = c.get(path + "-history").json()
    assert len(history) == 2
    assert json.loads(history[0]["before_json"])["extra"]["registration_purpose"] == "Follow-up"
    assert c.get(f"/api/v12/approved/candidates/{existing}/profile").json() == existing_before
    optional = c.post(
        "/api/v12/approved/registration",
        json={"candidate": {"full_name": "Optional purpose"}},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert optional.status_code == 201
    assert (
        c.get(f"/api/v12/approved/candidates/{optional.json()['id']}/profile")
        .json()["extra"]
        .get("registration_purpose")
        is None
    )
    with pytest.raises(Exception, match="immutable"):
        with transaction(engine) as conn:
            conn.execute(
                text("UPDATE candidates SET created_at='2000-01-01' WHERE id=:c"), {"c": cid}
            )


def test_email_extension_preserves_all_rows_schema_guards_and_is_idempotent(prepared):
    engine, _, cid = prepared
    with transaction(engine) as conn:
        conn.execute(
            text("UPDATE candidates SET current_salary_inr=12345.6789 WHERE id=:id"), {"id": cid}
        )
    before = snapshot(engine)
    registration_store.install(engine)
    after = snapshot(engine)
    assert all(after[1][name] == rows for name, rows in before[1].items())
    expected = {
        k: (registration_store.email_table(v) if k == ("table", "candidates") else v)
        for k, v in _objects((r[0], r[1], r[3]) for r in before[0]).items()
    }
    actual = _objects((r[0], r[1], r[3]) for r in after[0])
    assert all(actual[k] == v for k, v in expected.items())
    validate(engine)
    registration_store.install(engine)
    assert snapshot(engine) == after
    assert seed(engine, "Email accepted", "2026-11-20T00:00:00Z", "EMAIL")


def test_extension_failure_rolls_back_every_row_object_and_restores_foreign_keys(prepared):
    engine, _, _ = prepared
    before = snapshot(engine)
    with patch.object(
        registration_store,
        "_rows",
        side_effect=[before[1], RuntimeError("forced reconciliation failure")],
    ):
        with pytest.raises(RuntimeError, match="forced"):
            registration_store.install(engine)
    assert snapshot(engine) == before
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    validate(engine)


def test_source_extension_refuses_v2_or_nonisolated_path(v2, monkeypatch):
    engine, _, _, _, root = v2
    before = snapshot(engine)
    monkeypatch.setattr(config, "PROJECT_ENV_FILE", root / ".env")
    with pytest.raises(RuntimeError, match="isolated"):
        registration_store.install(engine)
    target = root / "runtime"
    target.mkdir()
    path = target / "v2.sqlite3"
    with sqlite3.connect(root / "isolated.sqlite3") as old, sqlite3.connect(path) as new:
        old.backup(new)
    copy = build_ats_engine(path)
    try:
        with pytest.raises(RuntimeError, match="V3"):
            registration_store.install(copy)
    finally:
        copy.dispose()
    assert snapshot(engine) == before


def test_selected_joined_and_not_joined_candidates_remain_in_directory(enabled):
    from test_unified_v12 import action, requirement

    from jobmitra.modules.ats_v2 import candidates, unified
    from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate

    engine, path, _ = enabled
    with engine.connect() as conn:
        company = conn.scalar(text("SELECT id FROM companies LIMIT 1"))
    ids = []
    for outcome in ["SELECT", "JOIN", "NOT_JOINED"]:
        candidate = candidates.create_candidate(
            engine, CandidateCreate(full_name="Outcome visibility " + outcome)
        )
        ids.append(candidate["id"])
        jid, lid = requirement((engine, company, None, candidate["id"], path.parent))
        unified.outcome(engine, jid, lid, action("SELECT"), "OPERATOR_TOKEN")
        if outcome == "JOIN":
            unified.outcome(
                engine,
                jid,
                lid,
                action("JOIN", confirmation_evidence="Synthetic confirmed joining"),
                "OPERATOR_TOKEN",
            )
        if outcome == "NOT_JOINED":
            unified.outcome(
                engine,
                jid,
                lid,
                action("NOT_JOINED", reason="Synthetic joining declined"),
                "OPERATOR_TOKEN",
            )
    result = registers.directory(engine, registers.Directory(q="Outcome visibility"))
    assert result["total"] == 3 and {r["id"] for r in result["items"]} == set(ids)

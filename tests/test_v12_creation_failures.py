"""Creation regressions on disposable PostgreSQL; no office source mutations."""

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from jobmitra.main import create_app

pytest_plugins = ["test_v12_postgres_backend"]


@pytest.fixture
def office(pg_store):
    config = pg_store[1].model_copy(
        update={
            "office_lan_enabled": True,
            "office_lan_cidrs": "127.0.0.1/32",
            "unified_v12_operator_token": None,
            "unified_v12_supervisor_token": None,
        }
    )
    with (
        patch("jobmitra.main.build_engine", return_value=Mock()),
        TestClient(
            create_app(config), base_url="http://127.0.0.1", client=("127.0.0.1", 40000)
        ) as client,
    ):
        client.headers.update({"X-Jobmitra-UI": "1", "Origin": "http://127.0.0.1"})
        yield client


def post(client, url, body, key=None):
    return client.post(url, json=body, headers={"Idempotency-Key": key or str(uuid4())})


def count(pg_store, table):
    with pg_store[0][0].connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


@pytest.mark.parametrize("period", ["MONTHLY", "ANNUAL"])
def test_registration_salary_fields_commit_and_replay(office, pg_store, period):
    body = {
        "candidate": {
            "full_name": "Synthetic Salary Candidate",
            "phone": "9876500012",
            "email": None,
            "job_title": "account",
            "experience_years": None,
            "current_salary_inr": 45000,
            "current_salary_period": period,
            "current_salary_basis": "CTC",
            "expected_salary_inr": 50000,
            "expected_salary_period": period,
            "expected_salary_basis": "CTC",
            "notice_days": None,
            "current_city": "Indore",
            "source": "FOUNDIT_PASTE",
        },
        "source_label": "Foundit",
        "notice_text": "45",
        "registration_purpose": None,
    }
    key = str(uuid4())
    response = post(office, "/api/v12/approved/registration", body, key)
    assert response.status_code == 201, response.text
    cid = response.json()["id"]
    replay = post(office, "/api/v12/approved/registration", body, key)
    assert replay.json() == {"id": cid, "replayed": True}
    person = office.get(f"/api/ats-v2/candidates/{cid}").json()
    for field, value in body["candidate"].items():
        assert person[field] == value
    with pg_store[0][0].connect() as conn:
        actual = (
            conn.execute(text("SELECT * FROM candidates WHERE id=:id"), {"id": cid})
            .mappings()
            .one()
        )
        assert actual["phone_normalized"] == "919876500012"
        assert actual["current_salary_inr"] == 45000 and actual["expected_salary_inr"] == 50000
        facts = json.loads(
            conn.execute(
                text(
                    "SELECT payload_json FROM recruitment_events WHERE candidate_id=:id "
                    "AND event_type='REGISTRATION_DETAILS'"
                ),
                {"id": cid},
            ).scalar_one()
        )
        assert facts["notice_text"] == "45" and facts["registration_purpose"] is None
        events = (
            conn.execute(
                text("SELECT event_type FROM recruitment_events WHERE candidate_id=:id"),
                {"id": cid},
            )
            .scalars()
            .all()
        )
        assert events.count("REQUEST_COMPLETED") == 1
        assert "CANDIDATE_CREATED" in events


@pytest.mark.parametrize("prefix", ["current", "expected"])
def test_amount_without_period_rollback_then_corrected_retry(office, pg_store, prefix):
    before = count(pg_store, "candidates")
    body = {"candidate": {"full_name": "Synthetic Missing Period", f"{prefix}_salary_inr": 0}}
    key = str(uuid4())
    r = post(office, "/api/v12/approved/registration", body, key)
    assert r.status_code == 422 and r.json()["code"] == prefix.upper() + "_SALARY_PERIOD_REQUIRED"
    assert count(pg_store, "candidates") == before
    body["candidate"][f"{prefix}_salary_period"] = "MONTHLY"
    assert post(office, "/api/v12/approved/registration", body, key).status_code == 201
    assert count(pg_store, "candidates") == before + 1


def test_optional_fields_blank_duplicate_phone_and_retry(office, pg_store):
    # The API needs a name; the approved quick form also asks for mobile.
    assert (
        post(
            office, "/api/v12/approved/registration", {"candidate": {"full_name": "Name Only"}}
        ).status_code
        == 201
    )
    body = {
        "candidate": {"full_name": "Synthetic Contact", "phone": "+91 98765 43210", "email": ""}
    }
    assert post(office, "/api/v12/approved/registration", body).status_code == 201
    body["candidate"]["phone"] = "9876543210"
    key = str(uuid4())
    before = count(pg_store, "candidates")
    r = post(office, "/api/v12/approved/registration", body, key)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_PHONE"
    body["candidate"]["phone"] = "9876543211"
    assert post(office, "/api/v12/approved/registration", body, key).status_code == 201
    assert count(pg_store, "candidates") == before + 1


def test_concurrent_candidate_duplicate_prevention(office, pg_store):
    body = {"candidate": {"full_name": "Concurrent Synthetic", "phone": "9876543212"}}
    before = count(pg_store, "candidates")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: post(office, "/api/v12/approved/registration", body), range(2))
        )
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert count(pg_store, "candidates") == before + 1


def job(pg_store):
    return {
        "company_id": pg_store[0][1],
        "title": "Synthetic Create JD",
        "target_date": "2030-01-01",
    }


@pytest.mark.parametrize("field", ["company_id", "title", "target_date"])
def test_jd_required_fields_then_corrected_retry(office, pg_store, field):
    body = job(pg_store)
    del body[field]
    key = str(uuid4())
    r = post(office, "/api/ats-v2/jobs", body, key)
    assert r.status_code == 422 and any(e["field"] == field for e in r.json()["field_errors"])
    assert count(pg_store, "job_descriptions") == 0
    body[field] = job(pg_store)[field]
    assert post(office, "/api/ats-v2/jobs", body, key).status_code == 201


def test_jd_optional_nulls_and_invalid_range_recovery(office, pg_store):
    body = {
        **job(pg_store),
        **dict.fromkeys(
            [
                "location",
                "work_mode",
                "vacancies",
                "company_contact",
                "experience_min",
                "experience_max",
                "qualification",
                "salary_min_inr",
                "salary_max_inr",
                "salary_period",
                "requirement_notes",
                "full_jd",
            ]
        ),
    }
    body["experience_min"] = 81
    key = str(uuid4())
    r = post(office, "/api/ats-v2/jobs", body, key)
    assert r.status_code == 422
    assert {
        "field": "experience_min",
        "message": "Please enter a value no greater than 80.",
    } in r.json()["field_errors"]
    body["experience_min"] = None
    response = post(office, "/api/ats-v2/jobs", body, key)
    assert response.status_code == 201, response.text
    actual = office.get(f"/api/ats-v2/jobs/{response.json()['id']}").json()
    assert all(actual[k] == v for k, v in body.items())


def test_jd_concurrent_distinct_and_same_key_retry(office, pg_store):
    body = job(pg_store)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: post(office, "/api/ats-v2/jobs", body, key), range(2)))
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert count(pg_store, "job_descriptions") == 1
    body["title"] = "Corrected Payload"
    assert post(office, "/api/ats-v2/jobs", body, key).status_code == 409
    assert post(office, "/api/ats-v2/jobs", body).status_code == 201
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda n: post(office, "/api/ats-v2/jobs", {**body, "title": f"Concurrent JD {n}"}),
                range(2),
            )
        )
    assert [r.status_code for r in responses] == [201, 201]
    assert count(pg_store, "job_descriptions") == 4
    with pg_store[0][0].connect() as conn:
        events = conn.execute(
            text(
                "SELECT event_type,count(*) FROM recruitment_events "
                "WHERE job_id IS NOT NULL GROUP BY event_type"
            )
        ).all()
        assert dict(events)["REQUEST_COMPLETED"] == 4
        assert dict(events)["JD_CREATED"] == 4


def test_safe_backend_feedback_and_office_policy(office, pg_store):
    r = post(
        office,
        "/api/v12/approved/registration",
        {"candidate": {"full_name": "Bad Field", "email": "private-invalid-value"}},
    )
    assert r.status_code == 422
    assert "private-invalid-value" not in r.text and "ValueError" not in r.text
    assert {"field": "email", "message": "Please enter a valid email address."} in r.json()[
        "field_errors"
    ]
    assert office.get("/api/v12/access").json()["office_lan"]
    before = count(pg_store, "candidates")
    assert (
        post(
            office,
            "/api/v12/approved/registration",
            {"candidate": {"full_name": "Blocked"}},
            key="bad",
        ).status_code
        == 422
    )
    r = office.post(
        "/api/v12/approved/registration",
        json={"candidate": {"full_name": "Blocked"}},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert r.status_code == 403
    assert count(pg_store, "candidates") == before

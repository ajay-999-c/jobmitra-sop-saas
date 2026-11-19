"""Synthetic end-to-end HTTP contracts for additive ATS and safe company failures."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.database import build_ats_engine, initialize
from jobmitra.modules.ats_v2.router import company_gateway

HEADERS = {"X-Jobmitra-UI": "1", "Origin": "http://testserver"}
API = "/api/ats-v2"


class FakeCompanies:
    def __init__(self):
        self.id = str(uuid4())
        self.available = True

    def options(self):
        if not self.available:
            raise AtsError("Company Master unavailable.", 503)
        return [{"id": self.id, "company_name": "Synthetic Company"}]

    def require(self, company_id):
        self.options()
        if str(company_id) != self.id:
            raise AtsError("Company not found.", 422)
        return self.options()[0]


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    path = tmp_path / "ats.sqlite3"
    engine = build_ats_engine(path)
    initialize(engine)
    engine.dispose()
    postgres = Mock()
    postgres.connect.side_effect = AssertionError("Real PostgreSQL is forbidden")
    monkeypatch.setattr("jobmitra.main.build_engine", lambda _: postgres)
    settings = Settings(
        _env_file=None,
        db_host="invalid.test",
        db_user="unused",
        db_name="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=path,
        ats_v2_resume_storage_root=tmp_path / "resumes",
    )
    app = create_app(settings)
    companies = FakeCompanies()
    sqlite = build_ats_engine(path)
    with sqlite.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO companies(id,company_name,company_name_key) "
                "VALUES(:id,'Synthetic Company','synthetic company')"
            ),
            {"id": companies.id},
        )
    sqlite.dispose()
    app.dependency_overrides[company_gateway] = lambda: companies
    with TestClient(app) as client:
        yield client, companies, path
    postgres.connect.assert_not_called()


def post(client, path, payload):
    return client.post(API + path, json=payload, headers=HEADERS)


def new_job(client, companies, **values):
    result = post(
        client,
        "/jobs",
        {
            "company_id": companies.id,
            "title": "Engineer",
            "target_date": (datetime.now(UTC) + timedelta(days=7)).date().isoformat(),
            "status": "ACTIVE",
            **values,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def new_candidate(client):
    result = post(client, "/candidates", {"full_name": "Synthetic Candidate", "skills": ["Python"]})
    assert result.status_code == 201, result.text
    return result.json()


def test_new_pages_and_existing_routes_do_not_collide(api_client):
    client, _, _ = api_client
    for route in ["/jd-workspace-v2", "/candidate-search-v2"]:
        response = client.get(route)
        assert response.status_code == 200
        assert 'href="/requirements"' in response.text
        assert 'href="/companies"' in response.text
        assert "recording-as" not in response.text
        assert "localStorage" not in response.text
        assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/email").status_code == 200
    assert client.get(API + "/health").json()["storage"] == "sqlite"
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/jobs" in paths and "/api/candidates" in paths
    assert "/api/ats-v2/jobs" in paths and "/api/ats-v2/candidates" in paths
    assert "delete" not in paths["/api/ats-v2/jobs/{job_id}"]
    assert str(client.app.url_path_for("ats_v2_health")) == API + "/health"
    assert str(client.app.url_path_for("health")) == "/api/resume-processing/health"
    operations = [
        operation["operationId"]
        for path, methods in paths.items()
        if path.startswith(API)
        for operation in methods.values()
    ]
    assert len(operations) == len(set(operations))
    assert all(name.startswith("ats_v2_") for name in operations)


def test_company_options_validation_and_gateway_outage(api_client):
    client, companies, path = api_client
    assert client.get(API + "/companies").json() == companies.options()
    invalid = post(
        client,
        "/jobs",
        {"company_id": str(uuid4()), "title": "Invalid", "target_date": "2030-01-01"},
    )
    assert invalid.status_code == 422
    job = new_job(client, companies)
    companies.available = False
    assert client.get(API + "/companies").status_code == 503
    assert (
        post(
            client,
            "/jobs",
            {"company_id": companies.id, "title": "Outage", "target_date": "2030-01-01"},
        ).status_code
        == 503
    )
    response = client.patch(
        API + f"/jobs/{job['id']}",
        headers=HEADERS,
        json={"company_id": str(uuid4()), "title": "Should not save"},
    )
    assert response.status_code == 503
    listing = client.get(API + "/jobs").json()
    assert listing["company_error"] and listing["total"] == 1
    assert listing["items"][0]["company_name"] is None
    assert listing["items"][0]["title"] == "Engineer"
    engine = build_ats_engine(path)
    with engine.connect() as conn:
        tables = (
            conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
            .scalars()
            .all()
        )
        assert "companies" in tables
        assert (
            conn.execute(text("SELECT company_id FROM job_descriptions")).scalar() == companies.id
        )
    engine.dispose()


def test_registration_profile_search_and_audit(api_client):
    client, _, _ = api_client
    candidate = new_candidate(client)
    cid = candidate["id"]
    patch = client.patch(
        API + f"/candidates/{cid}",
        headers=HEADERS,
        json={
            "skills": ["Python", "SQL"],
            "expected_salary_inr": 50000,
            "expected_salary_period": "MONTHLY",
            "expected_salary_basis": "CTC",
        },
    )
    assert patch.status_code == 200, patch.text
    result = client.get(API + "/candidates", params={"keywords": "Python SQL", "match": "ALL"})
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1
    rows = client.get(API + "/history", params={"candidate_id": cid}).json()["items"]
    changed = next(r for r in rows if r["event_type"] == "CANDIDATE_UPDATED")
    assert changed["after_json"]["skills_json"] == ["Python", "SQL"]
    assert changed["before_json"]["expected_salary_inr"] is None


def test_association_manual_stages_feedback_and_three_histories(api_client):
    client, companies, _ = api_client
    first, second = new_job(client, companies), new_job(client, companies)
    candidate = new_candidate(client)
    jid, cid = first["id"], candidate["id"]
    link = post(client, f"/jobs/{jid}/candidates", {"candidate_id": cid})
    assert link.status_code == 201
    lid = link.json()["id"]
    assert link.json()["stage_code"] == "POOL"
    assert post(client, f"/jobs/{jid}/candidates", {"candidate_id": cid}).status_code == 409
    assert (
        post(client, f"/jobs/{second['id']}/candidates", {"candidate_id": cid}).status_code == 201
    )
    invalid = post(client, f"/jobs/{jid}/candidates/{lid}/move", {"stage_code": "SELECTED"})
    assert invalid.status_code == 422
    moved = post(
        client,
        f"/jobs/{jid}/candidates/{lid}/move",
        {
            "stage_code": "CONTACT",
            "expected_stage": "POOL",
            "feedback": "Candidate confirmed availability.",
            "feedback_source": "CANDIDATE",
        },
    )
    assert moved.status_code == 200, moved.text
    assert (
        post(
            client,
            f"/jobs/{jid}/candidates/{lid}/move",
            {"stage_code": "SCREENING", "expected_stage": "POOL"},
        ).status_code
        == 409
    )
    assert (
        post(
            client, f"/jobs/{jid}/candidates/{lid}/move", {"stage_code": "NOT_SELECTED"}
        ).status_code
        == 200
    )
    row = client.get(API + f"/jobs/{jid}/pipeline").json()["items"][0]
    assert row["rejected_from_stage"] == "CONTACT"
    assert row["rejected_round_name"] == "Candidate Contact"
    assert row["next_stage"] is None
    assert (
        post(
            client, f"/jobs/{jid}/candidates/{lid}/feedback", {"feedback": "History retained."}
        ).status_code
        == 200
    )
    for query in [{"candidate_id": cid}, {"job_id": jid}, {"jd_candidate_id": lid}]:
        history = client.get(API + "/history", params=query).json()
        assert history["total"] > 0
        assert any(r["event_type"] == "REJECTED" for r in history["items"])
    history = client.get(API + "/history", params={"jd_candidate_id": lid}).json()["items"]
    assert sum(r["event_type"] == "MOVED" for r in history) == 1
    assert sum(r["event_type"] == "FEEDBACK" for r in history) == 2
    assert len(client.get(API + "/candidates").json()["items"]) == 1


def test_workflow_validation_stale_updates_and_activity_audit(api_client):
    client, companies, _ = api_client
    job, candidate = new_job(client, companies), new_candidate(client)
    jid, cid = job["id"], candidate["id"]
    assert post(client, f"/jobs/{jid}/candidates", {"candidate_id": cid}).status_code == 201
    response = client.put(
        API + f"/jobs/{jid}/workflow",
        headers=HEADERS,
        json={
            "workflow_mode": "CONFIGURED",
            "workflow_version": 0,
            "rounds": [{"round_name": "Technical", "mode": "VIDEO"}],
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["workflow_version"] == 1 and saved["rounds"][0]["id"]
    assert (
        client.put(
            API + f"/jobs/{jid}/workflow",
            headers=HEADERS,
            json={"workflow_mode": "DIRECT", "workflow_version": 0, "rounds": []},
        ).status_code
        == 409
    )
    assert client.get(API + f"/jobs/{jid}/pipeline").json()["items"][0]["stage_code"] == "POOL"
    created = post(
        client,
        f"/candidates/{cid}/activities",
        {
            "job_id": jid,
            "activity_type": "FOLLOW_UP",
            "due_at": "2030-01-02T10:00:00+05:30",
            "notes": "Call",
        },
    )
    assert created.status_code == 201, created.text
    aid = created.json()["id"]
    updated = client.patch(
        API + f"/activities/{aid}",
        headers=HEADERS,
        json={"job_id": jid, "activity_type": "FOLLOW_UP", "status": "DONE", "notes": "Called"},
    )
    assert updated.status_code == 200
    assert client.get(API + f"/candidates/{cid}/activities").json()[0]["status"] == "DONE"
    history = client.get(API + "/history", params={"candidate_id": cid}).json()["items"]
    assert any(r["event_type"] == "ACTIVITY_UPDATED" for r in history)


def test_resume_http_versions_review_and_download(api_client):
    client, _, _ = api_client
    candidate = new_candidate(client)
    cid = candidate["id"]
    data = b"%PDF-1.4\n synthetic\n%%EOF"
    uploaded = client.post(
        API + f"/candidates/{cid}/resumes",
        content=data,
        headers={
            **HEADERS,
            "Content-Type": "application/octet-stream",
            "X-Resume-Filename": "resume.pdf",
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    rid = uploaded.json()["id"]
    parsed = post(
        client,
        f"/candidates/{cid}/parsed-resume",
        {
            "source_resume_id": rid,
            "facts_reviewed": True,
            "profile": {"skills": ["Python"], "current_job_title": "Engineer"},
        },
    )
    assert parsed.status_code == 201, parsed.text
    generated = post(
        client,
        f"/candidates/{cid}/standardize",
        {"parsed_resume_id": parsed.json()["id"], "facts_reviewed": True},
    )
    assert generated.status_code == 201, generated.text
    download = client.get(API + f"/candidates/{cid}/resumes/{generated.json()['id']}/download")
    assert download.status_code == 200
    assert b"Synthetic Candidate" in download.content
    assert client.get(API + f"/candidates/{cid}/resumes/{rid}/download").content == data
    versions = client.get(API + f"/candidates/{cid}/resumes").json()
    assert len(versions) == 3
    assert all("storage_path" not in r for r in versions)
    history = client.get(API + "/history", params={"candidate_id": cid}).json()["items"]
    assert all("parsed_json" not in (r.get("after_json") or {}) for r in history)


def test_status_only_activity_patch_preserves_all_other_facts(api_client):
    client, companies, _ = api_client
    candidate, job = new_candidate(client), new_job(client, companies)
    cid, jid = candidate["id"], job["id"]
    assert post(client, f"/jobs/{jid}/candidates", {"candidate_id": cid}).status_code == 201
    original = post(
        client,
        f"/candidates/{cid}/activities",
        {
            "job_id": jid,
            "activity_type": "INTERVIEW",
            "notes": "Keep the scheduled details",
            "due_at": "2030-01-02T10:00:00+05:30",
        },
    ).json()
    response = client.patch(
        API + f"/activities/{original['id']}", headers=HEADERS, json={"status": "DONE"}
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["status"] == "DONE"
    for key in ("job_id", "activity_type", "notes", "due_at", "occurred_at"):
        assert updated[key] == original[key]


def test_same_origin_body_limits_and_safe_errors(api_client):
    client, _, _ = api_client
    assert client.post(API + "/candidates", json={"full_name": "Example"}).status_code == 403
    assert (
        client.post(
            API + "/candidates",
            headers={**HEADERS, "Origin": "https://other.test"},
            json={"full_name": "Example"},
        ).status_code
        == 403
    )
    response = post(
        client, "/candidates", {"full_name": "Example", "email": "private-invalid-contact"}
    )
    assert response.status_code == 422 and "private-invalid-contact" not in response.text
    assert (
        client.post(
            API + "/candidates",
            headers={**HEADERS, "Content-Type": "application/json"},
            content=b"x" * 512001,
        ).status_code
        == 413
    )
    assert client.get(API + "/candidates/999999").status_code == 404
    assert client.get(API + "/jobs/999999").status_code == 404


def test_disabled_or_uninitialized_ats_never_creates_database(tmp_path, monkeypatch):
    postgres = Mock()
    monkeypatch.setattr("jobmitra.main.build_engine", lambda _: postgres)
    path = tmp_path / "missing.sqlite3"
    settings = Settings(
        _env_file=None,
        db_host="invalid.test",
        db_user="unused",
        db_name="unused",
        db_password="unused",
        ats_v2_database=path,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/jd-workspace-v2").status_code == 404
        assert client.get(API + "/candidates").status_code == 404
        assert client.get("/health/live").status_code == 200
    settings.ats_v2_enabled = True
    with TestClient(create_app(settings)) as client:
        assert client.get(API + "/health").status_code == 503
        assert client.get("/health/live").status_code == 200
    assert not path.exists()

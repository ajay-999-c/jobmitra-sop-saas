"""Quick entry against disposable PostgreSQL only; no Alembic execution."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from jobmitra.core.config import Settings
from jobmitra.core.database import Base, build_engine
from jobmitra.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("JOBMITRA_STAGE3_DISPOSABLE") != "1", reason="Disposable runner required"
)


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, document_storage_root=tmp_path)
    assert settings.db_host.startswith("/private/tmp/jobmitra-stage2-")
    assert Path(settings.db_host).name == "socket"
    app = create_app(settings)
    engine = build_engine(settings)
    # Test-only tables on the isolated Unix socket, never migrations or Windows.
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        client.headers["X-Jobmitra-UI"] = "1"
        yield client, engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def save(client, **fields):
    result = client.post(
        "/api/candidates",
        json={
            "full_name": "Synthetic quick candidate",
            "mobile": "000123456789",
            "source": "Other",
            "record_initial_visit": False,
            **fields,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_minimal_and_walkin_without_visit(client):
    api, engine = client
    minimal = save(api)
    walkin = save(api, mobile="000123456788", source="Walk-in")
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, source, experience_months, qualification FROM candidates")
        ).all()
        assert len(rows) == 2
        assert all(row.experience_months is None and row.qualification is None for row in rows)
        assert conn.scalar(text("SELECT count(*) FROM candidate_visits")) == 0
    assert minimal["source"] == "Other"
    assert walkin["source"] == "Walk-in"


def test_all_fields_persist_and_history_unchanged(client):
    api, engine = client
    domain = api.post("/api/domains", json={"name": "Synthetic domain"}).json()
    sub = api.post(
        "/api/subdomains", json={"domain_id": domain["id"], "name": "Synthetic sub"}
    ).json()
    historical = save(
        api,
        qualification="Preserved qualification",
        skills=["Python"],
        hometown="Original town",
        domain_id=domain["id"],
        subdomain_id=sub["id"],
        preferred_locations=["Original city"],
        ready_to_relocate=False,
        home_state="Madhya Pradesh",
        experience_months=42,
        current_salary_amount="60000.00",
        current_salary_period="Monthly",
        current_salary_basis="Gross",
        last_salary_raw="Original salary wording",
        source="Existing database",
    )
    values = dict(
        full_name="Synthetic complete",
        mobile="000123456788",
        email="synthetic@example.invalid",
        role_title="Engineer",
        experience_months=30,
        current_salary_amount="50000.25",
        current_salary_period="Monthly",
        current_salary_basis="CTC",
        expected_salary_amount="900000.00",
        expected_salary_period="Annual",
        expected_salary_basis="CTC",
        notice_period_text="30 days",
        current_location="Synthetic city",
        source="Referral",
    )
    row = save(api, **values)
    with engine.connect() as conn:
        stored = (
            conn.execute(text("SELECT * FROM candidates WHERE id=:id"), {"id": row["id"]})
            .mappings()
            .one()
        )
        for key, value in values.items():
            assert str(stored[key]) == str(value)
    assert api.get("/api/candidates/" + historical["id"]).json() == historical
    patched = api.patch(
        "/api/candidates/" + historical["id"],
        json={"version": historical["version"], "role_title": "Updated job"},
    )
    assert patched.status_code == 200
    assert patched.json()["qualification"] == historical["qualification"]
    assert patched.json()["skills"] == historical["skills"]
    assert patched.json()["hometown"] == historical["hometown"]
    for field, value in historical.items():
        if field not in {"role_title", "version", "updated_at"}:
            assert patched.json()[field] == value, field
    unchanged = api.patch(
        "/api/candidates/" + historical["id"], json={"version": patched.json()["version"]}
    )
    assert unchanged.status_code == 200
    assert unchanged.json() == patched.json()
    assert api.get("/domains").status_code == 200
    assert 'name="domain_id"' in api.get("/candidates/" + historical["id"]).text
    assert api.get("/candidates/" + row["id"]).status_code == 200
    assert api.get("/api/candidates/" + row["id"] + "/documents").json() == []


def test_duplicate_mobile_and_email(client):
    api, _ = client
    row = save(api, email="synthetic@example.invalid")
    for fields in ({"mobile": row["mobile"]}, {"mobile": "000123456788", "email": row["email"]}):
        response = api.post(
            "/api/candidates", json={"full_name": "Duplicate", "source": "Other", **fields}
        )
        assert response.status_code == 409
    response = api.get("/api/candidates/duplicates", params={"email": row["email"]})
    assert response.status_code == 200
    assert response.json()[0]["id"] == row["id"]


def test_add_only_simplified_edit_and_walkin_preserved(client):
    api, _ = client
    html = api.get("/candidates/new").text
    assert "data-quick-candidate" in html
    assert 'name="qualification"' not in html
    assert 'name="domain_id"' not in html
    assert 'name="experience_months"' in html
    row = save(api, qualification="Retain me")
    edit = api.get("/candidates/" + row["id"]).text
    assert 'name="qualification"' in edit
    assert "Retain me" in edit
    walkin = api.get("/candidates/new?walkin=true").text
    assert "data-quick-candidate" not in walkin
    assert 'name="qualification"' in walkin
    # Existing explicit walk-in registration still records the initial visit.
    response = api.post(
        "/api/candidates",
        json={"full_name": "Explicit walk-in", "mobile": "000123456788", "source": "Walk-in"},
    )
    assert response.status_code == 201
    with client[1].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM candidate_visits")) == 1


def test_existing_document_and_job_search_workflows(client):
    from test_stage3 import PDF

    api, _ = client
    staff = api.post("/api/staff", json={"display_name": "Synthetic worker"}).json()
    row = save(api, initial_job_search={"desired_role": "Tester", "assigned_staff_id": staff["id"]})
    searches = api.get("/api/job-search-requests").json()
    assert searches[0]["candidate_id"] == row["id"]
    updated = api.patch(
        "/api/job-search-requests/" + searches[0]["id"],
        json={"version": searches[0]["version"], "status": "On Hold"},
    )
    assert updated.status_code == 200
    uploaded = api.post(
        "/api/candidates/" + row["id"] + "/documents?kind=ORIGINAL_RESUME",
        content=PDF,
        headers={
            "X-Document-Filename": "synthetic.pdf",
            "Content-Type": "application/octet-stream",
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    downloaded = api.get(
        "/candidates/" + row["id"] + "/documents/" + uploaded.json()["id"] + "/download"
    )
    assert downloaded.content == PDF
    assert api.get("/candidates/foundit-import").status_code == 200
    assert api.get("/office-visits").status_code == 200


@pytest.mark.parametrize(
    "source", ["Walk-in", "Foundit", "WhatsApp", "Referral", "Other", "Existing database"]
)
def test_existing_sources_are_persisted(client, source):
    api, engine = client
    row = save(api, source=source)
    with engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT source FROM candidates WHERE id=:id"), {"id": row["id"]})
            == source
        )
        assert conn.scalar(text("SELECT count(*) FROM candidate_visits")) == 0


@pytest.mark.parametrize("source", ["Email", "Naukri"])
def test_unsupported_sources_disabled_and_rejected(client, source):
    api, _ = client
    import re

    html = api.get("/candidates/new").text
    assert re.search(r'<option value="' + source + r'"[^>]*disabled', html)
    response = api.post(
        "/api/candidates",
        json={"full_name": "Synthetic", "mobile": "000123456789", "source": source},
    )
    assert response.status_code == 422
    assert api.get("/api/candidates").json() == []


@pytest.mark.parametrize("months", [-1, 1.5])
def test_experience_requires_nonnegative_whole_months(client, months):
    api, _ = client
    response = api.post(
        "/api/candidates",
        json={
            "full_name": "Synthetic",
            "mobile": "000123456789",
            "source": "Other",
            "experience_months": months,
        },
    )
    assert response.status_code == 422

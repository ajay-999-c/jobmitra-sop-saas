"""Catalog and paste workflows; never run against the office database."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from test_foundit_parser import SAMPLE
from test_stage2 import database as database
from test_stage3 import create, employee, upload
from test_stage3 import desk as desk

pytestmark = pytest.mark.skipif(
    os.getenv("JOBMITRA_STAGE3_DISPOSABLE") != "1", reason="Disposable runner required"
)


def snapshot(connection):
    tables = connection.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    ).scalars()
    return {
        name: connection.execute(
            text(f'SELECT to_jsonb(t)::text FROM "{name}" t ORDER BY to_jsonb(t)::text')
        )
        .scalars()
        .all()
        for name in tables
    }


def test_parse_is_zero_write_and_static_routes(desk):
    client, connection, _ = desk
    before = snapshot(connection)
    response = client.post("/api/candidates/foundit/preview", json={"raw": SAMPLE})
    assert response.status_code == 200, response.text
    assert response.json()["fields"]["experience_months"] == 63
    assert client.post("/api/candidates/foundit/preview", json={"raw": SAMPLE}).status_code == 200
    assert snapshot(connection) == before
    html = client.get("/candidates/foundit-import")
    assert html.status_code == 200
    assert "Foundit WhatsApp Paste" in html.text
    assert "Save Candidate" in html.text
    assert "data-catalog-picker" in html.text


def test_confirm_create_repeat_duplicate_email_phone_and_selective_update(desk):
    client, connection, root = desk
    actor = employee(client)
    payload = {
        "full_name": "Synthetic Paste Candidate",
        "mobile": "9876543210",
        "email": "PASTE@EXAMPLE.COM",
        "source": "Foundit",
        "confirmed": True,
        "recorded_by_staff_id": actor,
        "skills": ["Excel"],
        "qualification": "Confirmed BCom",
    }
    counts = {
        t: connection.scalar(text(f"SELECT count(*) FROM {t}"))
        for t in ("candidate_visits", "job_search_requests")
    }
    response = client.post("/api/candidates/foundit/confirm", json=payload)
    assert response.status_code == 201, response.text
    candidate = response.json()
    assert candidate["email"] == "paste@example.com"
    assert client.get("/api/candidates/" + candidate["id"]).json() == candidate
    for override in ({}, {"mobile": "+91 9876543210"}, {"mobile": "8765432109"}):
        assert (
            client.post("/api/candidates/foundit/confirm", json={**payload, **override}).status_code
            == 409
        )
    matches = client.get(
        "/api/candidates/duplicates", params={"email": " Paste@Example.com "}
    ).json()
    assert [row["id"] for row in matches] == [candidate["id"]]
    assert (
        client.post(
            "/api/candidates/foundit/confirm", json={**payload, "confirmed": False}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/candidates/foundit/confirm", json={**payload, "initial_job_search": {}}
        ).status_code
        == 422
    )
    doc = upload(client, candidate)
    assert doc.status_code == 201
    before = snapshot(connection)
    files = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    patch = {
        "version": candidate["version"],
        "confirmed": True,
        "recorded_by_staff_id": actor,
        "role_title": "Reviewed Analyst",
    }
    response = client.patch(f"/api/candidates/foundit/{candidate['id']}/confirm", json=patch)
    assert response.status_code == 200, response.text
    after_candidate = response.json()
    for key in candidate.keys() - {"role_title", "version", "updated_at"}:
        assert after_candidate[key] == candidate[key], key
    after = snapshot(connection)
    for table in before.keys() - {"candidates"}:
        assert before[table] == after[table], table
    assert files == {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert (
        client.patch(f"/api/candidates/foundit/{candidate['id']}/confirm", json=patch).status_code
        == 409
    )
    assert counts == {t: connection.scalar(text(f"SELECT count(*) FROM {t}")) for t in counts}


def test_conflicting_matches_and_placeholder_rejected(desk):
    client, _, _ = desk
    actor = employee(client)
    first = create(client, mobile="9876543210", email="one@example.com")
    second = create(client, mobile="8765432109", email="two@example.com")
    rows = client.get(
        "/api/candidates/duplicates", params={"mobile": first["mobile"], "email": second["email"]}
    ).json()
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    response = client.patch(
        f"/api/candidates/foundit/{first['id']}/confirm",
        json={
            "version": first["version"],
            "confirmed": True,
            "recorded_by_staff_id": actor,
            "email": second["email"],
        },
    )
    assert response.status_code == 409
    response = client.post(
        "/api/candidates/foundit/confirm",
        json={
            "full_name": "name",
            "mobile": "7654321098",
            "confirmed": True,
            "recorded_by_staff_id": actor,
        },
    )
    assert response.status_code == 422


def test_shared_catalog_company_uuid_and_legacy_fields(desk):
    client, connection, _ = desk
    actor = employee(client)
    company = client.get("/api/companies").json()[0]
    domain = client.post("/api/domains", json={"name": "Synthetic Sales"}).json()
    sub = client.post(
        "/api/subdomains", json={"name": "Field Sales", "domain_id": domain["id"]}
    ).json()
    other = client.post("/api/domains", json={"name": "Synthetic Finance"}).json()
    assert client.post("/api/domains", json={"name": "  synthetic   SALES "}).status_code == 409
    payload = {
        "company_id": company["id"],
        "actor_staff_id": actor,
        "job_title": "Free text role",
        "domain_id": domain["id"],
        "subdomain_id": sub["id"],
        "domain_key": "Legacy label",
        "subdomain_key": "Legacy sub label",
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 201, response.text
    jd = response.json()
    candidate = create(client, domain_id=domain["id"], subdomain_id=sub["id"])
    for route in (
        "/requirements/new",
        f"/requirements/{jd['id']}",
        f"/candidates/{candidate['id']}",
    ):
        html = client.get(route)
        assert html.status_code == 200, html.text
        assert domain["id"] in html.text and sub["id"] in html.text
        assert "data-picker-search" in html.text and "Add New Domain" in html.text
    # Quick Entry intentionally omits catalog inputs; detailed editing keeps them.
    quick = client.get("/candidates/new")
    assert quick.status_code == 200
    assert 'name="domain_id"' not in quick.text
    assert 'name="subdomain_id"' not in quick.text
    assert client.post("/api/jobs", json={**payload, "domain_id": other["id"]}).status_code == 422
    assert client.post("/api/jobs", json={**payload, "company_id": str(uuid4())}).status_code == 422
    assert (
        client.post("/api/jobs", json={**payload, "company_id": "Made up company"}).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/candidates/" + candidate["id"],
            json={"version": candidate["version"], "domain_id": other["id"]},
        ).status_code
        == 422
    )
    client.patch("/api/domains/" + domain["id"], json={"name": "Renamed Sales", "is_active": False})
    patch = {"actor_staff_id": actor, "version": jd["version"], "job_title": "Updated title"}
    response = client.patch("/api/jobs/" + jd["id"], json=patch)
    assert response.status_code == 200
    assert response.json()["domain_key"] == "Legacy label"
    assert response.json()["domain_id"] == domain["id"]
    assert client.post("/api/jobs", json=payload).status_code == 422
    current = client.get("/api/companies/" + company["id"]).json()
    company_input = {
        key: current[key]
        for key in (
            "company_name",
            "general_phone_numbers",
            "address_line",
            "city",
            "state",
            "postal_code",
            "contacts",
            "updated_at",
        )
    }
    company_input["company_name"] = "Renamed Company for JD"
    assert client.put("/api/companies/" + company["id"], json=company_input).status_code == 200
    detail = client.get("/api/jobs/" + jd["id"]).json()
    assert (
        detail["company_id"] == company["id"] and detail["company_name"] == "Renamed Company for JD"
    )


def test_catalog_migration_preserves_all_historical_columns(desk):
    client, connection, _ = desk
    actor = employee(client)
    company = client.get("/api/companies").json()[0]
    client.post(
        "/api/jobs",
        json={
            "actor_staff_id": actor,
            "company_id": company["id"],
            "job_title": "Legacy",
            "domain_key": "Do not map automatically",
            "required_skills": ["SQL"],
            "salary_currency": "USD",
            "salary_min": "2000",
        },
    )
    cfg = Config("alembic.ini")
    cfg.attributes["connection"] = connection
    command.downgrade(cfg, "0005_jd_general_skills")
    before = snapshot(connection)
    command.upgrade(cfg, "0006_jd_catalog_links")
    after = snapshot(connection)
    for table in before.keys() - {"job_requirements", "alembic_version"}:
        assert before[table] == after[table], table
    import json

    for old, new in zip(before["job_requirements"], after["job_requirements"], strict=True):
        new = json.loads(new)
        assert new.pop("domain_id") is None and new.pop("subdomain_id") is None
        assert new == json.loads(old)


def test_reviewed_supported_values_and_unsupported_fields_are_not_silently_accepted(desk):
    client, _, _ = desk
    actor = employee(client)
    preview = client.post(
        "/api/candidates/foundit/preview",
        json={
            "raw": "Name: Synthetic Reviewer\nTotal experience: 5y 3m\n"
            "Education: BCom, Example University, 2024\n"
            "Ready to relocate: Yes\nCurrent industry: Retail\n9876543210\nperson@example.com"
        },
    ).json()
    assert preview["preview_only"]["institution"] == "Example University"
    payload = {
        **{key: value for key, value in preview["fields"].items() if value is not None},
        "full_name": "Employee Edited Name",
        "experience_months": 64,
        "qualification": "Employee confirmed BCom - Finance",
        "confirmed": True,
        "recorded_by_staff_id": actor,
    }
    # Unsupported details cannot disappear inside an accepted request.
    rejected = client.post(
        "/api/candidates/foundit/confirm", json={**payload, "industry": "Retail"}
    )
    assert rejected.status_code == 422
    response = client.post("/api/candidates/foundit/confirm", json=payload)
    assert response.status_code == 201, response.text
    candidate = client.get("/api/candidates/" + response.json()["id"]).json()
    assert candidate["full_name"] == "Employee Edited Name"
    assert candidate["experience_months"] == 64
    assert candidate["qualification"] == "Employee confirmed BCom - Finance"
    assert candidate["ready_to_relocate"] is True

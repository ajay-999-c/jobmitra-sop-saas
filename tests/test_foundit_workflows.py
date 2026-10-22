"""Catalog and paste workflows; never run against the office database."""

import os

import pytest
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
    assert "Save Reviewed Changes" in html.text
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
            "/api/candidates/foundit/confirm", json={**payload, "confirm_duplicate": True}
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

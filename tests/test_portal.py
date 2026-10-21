"""Unified navigation using only the guarded disposable Stage 3 fixture."""

import os
import re

import pytest
from sqlalchemy.exc import ProgrammingError
from test_stage2 import database as database
from test_stage3 import create, employee
from test_stage3 import desk as desk

from jobmitra.modules.candidates import repository as candidate_repository

pytestmark = pytest.mark.skipif(
    os.getenv("JOBMITRA_STAGE3_DISPOSABLE") != "1", reason="Disposable database required"
)


def test_shared_navigation_routes_and_company_jd_relationship(desk):
    client, _, _ = desk
    actor = employee(client)
    company = client.get("/api/companies").json()[0]
    jd = client.post(
        "/api/jobs",
        json={
            "company_id": company["id"],
            "job_title": "Portal test JD",
            "actor_staff_id": actor,
        },
    )
    assert jd.status_code == 201, jd.text
    jd = jd.json()
    candidate = create(client)
    assert client.get("/", follow_redirects=False).headers["location"] == "/overview"
    for route, active in [
        ("/overview", "/overview"),
        ("/companies", "/companies"),
        ("/requirements", "/requirements"),
        (f"/requirements/{jd['id']}", "/requirements"),
        ("/candidate-desk", "/candidate-desk"),
        (f"/candidates/{candidate['id']}", "/candidate-desk"),
        ("/office-visits", "/candidate-desk"),
        ("/job-search-requests", "/candidate-desk"),
        ("/domains", "/candidate-desk"),
        ("/staff", "/staff"),
        ("/tasks", "/tasks"),
    ]:
        response = client.get(route)
        assert response.status_code == 200, response.text
        nav = re.search(r'<nav class="global-nav".*?</nav>', response.text, re.S).group()
        assert f'href="{active}" aria-current="page"' in nav
        assert nav.count('aria-current="page"') == 1
        assert response.text.count('id="recording-as"') == 1
        assert actor in response.text
        assert 'class="sidebar"' not in response.text
        assert "<iframe" not in response.text and ":8766" not in response.text
    page = client.get(f"/requirements?company_id={company['id']}")
    assert "Portal test JD" in page.text and "Back to company" in page.text
    assert client.get(f"/api/jobs?company_id={company['id']}").json()[0]["id"] == jd["id"]
    other = client.get("/api/companies").json()[1]
    assert client.get(f"/api/jobs?company_id={other['id']}").json() == []
    detail = client.get(f"/requirements/{jd['id']}").text
    assert f"/companies?company_id={company['id']}" in detail
    assert "Candidate Contact" in detail and "Open Candidate Desk" in detail
    for route in ["/requirements", "/candidates", "/tasks"]:
        fragment = client.get(route, headers={"HX-Request": "true"})
        assert fragment.status_code == 200
        assert "global-nav" not in fragment.text and "<html" not in fragment.text


def test_missing_candidate_schema_keeps_navigation_and_api_contract(desk, monkeypatch):
    client, _, _ = desk

    def unavailable(*args, **kwargs):
        raise ProgrammingError("redacted", {}, Exception("private driver details"))

    monkeypatch.setattr(candidate_repository, "candidates", unavailable)
    response = client.get("/candidates")
    assert response.status_code == 503
    assert "global-nav" in response.text and "migration is pending" in response.text
    assert "private driver details" not in response.text
    response = client.get("/api/candidates")
    assert response.status_code == 503 and "detail" in response.json()


def test_overview_truthfully_handles_undeployed_candidate_table(desk):
    client, connection, _ = desk
    # Transactional DDL in the disposable fixture only; restored by outer rollback.
    connection.exec_driver_sql("ALTER TABLE candidates RENAME TO candidates_not_deployed")
    response = client.get("/overview")
    assert response.status_code == 200
    assert "Database unavailable or setup pending" in response.text
    assert 'href="/companies"' in response.text
    assert client.get("/companies").status_code == 200
    response = client.get("/candidates")
    assert response.status_code == 503 and "global-nav" in response.text

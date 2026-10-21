"""Focused UI/API checks using synthetic rows inside a rolled-back transaction; no DDL."""

import json
import os
import re
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from jobmitra.core.config import Settings
from jobmitra.core.database import build_engine, get_session
from jobmitra.main import create_app
from jobmitra.modules.companies.models import Company, CompanyContact


def test_local_assets_and_invalid_inputs_without_database():
    app = create_app()
    app.dependency_overrides[get_session] = lambda: MagicMock()
    with TestClient(app) as client:
        assert client.get("/", follow_redirects=False).headers["location"] == "/overview"
        for name in ("directory.css", "directory.mjs", "search.mjs"):
            response = client.get(f"/static/companies/{name}")
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
        assert client.post("/api/companies", json={"company_name": "x"}).status_code == 403
        assert (
            client.post(
                "/api/companies",
                json={"company_name": "x"},
                headers={
                    "X-Jobmitra-UI": "1",
                    "Origin": "https://other.invalid",
                },
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/companies",
                json={"company_name": "   "},
                headers={
                    "X-Jobmitra-UI": "1",
                },
            ).status_code
            == 422
        )
    app.dependency_overrides.clear()


@pytest.fixture
def ui():
    if os.getenv("JOBMITRA_RUN_UI_TESTS") != "1":
        pytest.skip("Opt in to transaction-isolated UI tests with JOBMITRA_RUN_UI_TESTS=1")
    settings = Settings()
    assert settings.db_name == "jobmitra_dev"
    assert settings.db_host in {"127.0.0.1", "localhost", "::1"}
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            app = create_app(settings)

            def session():
                with Session(connection, join_transaction_mode="create_savepoint") as value:
                    yield value

            app.dependency_overrides[get_session] = session
            try:
                with TestClient(app) as client:
                    client.headers["X-Jobmitra-UI"] = "1"
                    yield client, connection
            finally:
                app.dependency_overrides.clear()
                transaction.rollback()
    finally:
        engine.dispose()


def add(client, name=None, **fields):
    response = client.post(
        "/api/companies",
        json={
            "company_name": name or f"UI Test {uuid4()}",
            **fields,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def editable(company):
    return {
        name: company[name]
        for name in (
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


def test_directory_embeds_one_lightweight_snapshot_and_never_loads_contacts(ui):
    client, connection = ui
    company = add(
        client,
        general_phone_numbers=["01111111111"],
        contacts=[
            {
                "contact_name": "PRIVATE CONTACT TEXT",
                "phone_numbers": ["02222222222"],
            }
        ],
    )
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(connection, "before_cursor_execute", capture)
    try:
        response = client.get("/companies")
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "PRIVATE CONTACT TEXT" not in response.text
    assert "02222222222" not in response.text and "01111111111" not in response.text
    blob = re.search(
        r'<script id="directory-data" type="application/json">(.*?)</script>', response.text, re.S
    ).group(1)
    rows = json.loads(blob)
    assert any(row["id"] == company["id"] for row in rows)
    assert all(set(row) == {"id", "company_name"} for row in rows)
    selects = [s for s in statements if s.lstrip().startswith("select")]
    assert len(selects) == 1
    assert "company_contacts" not in selects[0]
    assert "general_phone_numbers" not in selects[0]
    assert (
        client.get(f"/api/companies/{company['id']}").json()["contacts"][0]["contact_name"]
        == "PRIVATE CONTACT TEXT"
    )


def test_create_edit_contacts_and_nullable_address_preserve_ids(ui):
    client, connection = ui
    company = add(client, contacts=[{"contact_name": None}, {"contact_name": "Second"}])
    assert company["general_phone_numbers"] == [] and company["source_register_ids"] == []
    assert company["city"] is None
    first_id = company["contacts"][0]["id"]
    payload = editable(company)
    payload.update(
        company_name=f"Renamed UI {uuid4()}",
        postal_code="001234",
        general_phone_numbers=["01234567890", "01234567890"],
    )
    payload["contacts"] = [
        {**company["contacts"][0], "contact_name": "Edited", "phone_numbers": ["09876543210"]},
        {"contact_name": "New", "designation": "HR", "phone_numbers": []},
    ]
    response = client.put(f"/api/companies/{company['id']}", json=payload)
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["id"] == company["id"]
    assert first_id in {c["id"] for c in changed["contacts"]}
    assert len(changed["contacts"]) == 2
    assert changed["general_phone_numbers"] == ["01234567890"]
    assert changed["postal_code"] == "001234" and changed["city"] is None
    assert changed["updated_at"] != company["updated_at"]
    assert (
        connection.scalar(
            select(CompanyContact).where(CompanyContact.id == company["contacts"][1]["id"])
        )
        is None
    )


def test_stale_save_and_delete_do_not_overwrite_another_employee(ui):
    client, _ = ui
    company = add(client)
    payload = editable(company)
    payload["city"] = "New city"
    changed = client.put(f"/api/companies/{company['id']}", json=payload).json()
    assert client.put(f"/api/companies/{company['id']}", json=payload).status_code == 409
    assert (
        client.request(
            "DELETE",
            f"/api/companies/{company['id']}",
            json={
                "updated_at": company["updated_at"],
            },
        ).status_code
        == 409
    )
    assert client.get(f"/api/companies/{company['id']}").json()["city"] == "New city"
    assert changed["updated_at"] != company["updated_at"]


def test_duplicate_name_failure_rolls_back_and_connection_remains_usable(ui):
    client, _ = ui
    name = f"Duplicate UI {uuid4()}"
    existing = add(client, name)
    response = client.post("/api/companies", json={"company_name": name.upper()})
    assert response.status_code == 409
    assert response.json()["detail"] == "A company with this name already exists."
    assert client.get(f"/api/companies/{existing['id']}").status_code == 200


def test_contact_ownership_and_readonly_source_ids(ui):
    client, connection = ui
    first = add(client, contacts=[{"contact_name": "Owner"}])
    second = add(client)
    payload = editable(second)
    payload["contacts"] = first["contacts"]
    assert client.put(f"/api/companies/{second['id']}", json=payload).status_code == 422
    payload["contacts"] = []
    payload["source_register_ids"] = ["FORGED"]
    assert client.put(f"/api/companies/{second['id']}", json=payload).status_code == 422
    assert (
        connection.scalar(select(Company.source_register_ids).where(Company.id == second["id"]))
        == []
    )


def test_delete_removes_only_the_selected_company_and_its_contacts(ui):
    client, _ = ui
    first = add(client, contacts=[{"contact_name": "Test"}])
    second = add(client)
    response = client.request(
        "DELETE",
        f"/api/companies/{first['id']}",
        json={
            "updated_at": first["updated_at"],
        },
    )
    assert response.status_code == 204
    assert client.get(f"/api/companies/{first['id']}").status_code == 404
    assert client.get(f"/api/companies/{second['id']}").status_code == 200


def test_template_escapes_names_and_refreshed_list_includes_changes(ui):
    client, _ = ui
    name = f'<img src=x onerror="alert(1)"> {uuid4()}'
    company = add(client, name)
    html = client.get("/companies").text
    assert "<img src=x" not in html
    snapshot = client.get("/api/companies")
    assert snapshot.headers["cache-control"] == "no-store"
    assert {"id": company["id"], "company_name": name} in snapshot.json()

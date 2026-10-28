"""Candidate lookup against a guarded disposable PostgreSQL database only."""

import os

import pytest
from sqlalchemy import text
from test_stage2 import database as database
from test_stage3 import create
from test_stage3 import desk as desk

pytestmark = pytest.mark.skipif(
    os.getenv("JOBMITRA_STAGE3_DISPOSABLE") != "1",
    reason="Use scripts/test_stage3_isolated.py; never a real database",
)


@pytest.mark.parametrize("query", ["Radhe", "RADHE", "dhe", "Radhe Kumar"])
def test_partial_names(desk, query):
    client, _, _ = desk
    first = create(client, full_name="Radhe Kumar", mobile="9876543210")
    create(client, full_name="Radhesh Sharma", mobile="8765432109")
    rows = client.get("/api/candidates", params={"q": query}).json()
    assert first["id"] in [row["id"] for row in rows]
    assert len(rows) == (1 if query == "Radhe Kumar" else 2)


@pytest.mark.parametrize(
    "query",
    [
        "9876543210",
        "+91 98765-43210",
        "919876543210",
        "0091-98765-43210",
        "7654",
        "+91 7654",
        "(98765) 43210",
    ],
)
def test_phone_formats_and_exact_priority(desk, query):
    client, _, _ = desk
    first = create(client, full_name="Zed Synthetic", mobile="+91 98765-43210")
    create(client, full_name="Alpha Synthetic", mobile="987654321099")
    rows = client.get("/api/candidates", params={"q": query}).json()
    assert first["id"] in [row["id"] for row in rows]
    if len("".join(c for c in query if c.isdigit())) >= 10:
        assert rows[0]["id"] == first["id"]


def test_limits_paging_literal_queries_and_no_writes(desk):
    client, connection, _ = desk
    for i in range(23):
        create(client, full_name=f"Lookup Synthetic {i:02}", mobile=f"987654{i:04}")
    before = connection.execute(
        text("SELECT id, full_name, mobile, version FROM candidates ORDER BY id")
    ).all()
    first = client.get("/api/candidates").json()
    second = client.get("/api/candidates", params={"offset": 20}).json()
    assert len(first) == 20 and len(second) == 3
    assert not {x["id"] for x in first} & {x["id"] for x in second}
    for query in ["123", "+91 12", "%", "_", "' OR 1=1 --", "NothingMatches"]:
        assert client.get("/api/candidates", params={"q": query}).json() == []
    assert client.get("/api/candidates?limit=21").status_code == 422
    assert client.get("/candidates?offset=-1").status_code == 422
    assert (
        before
        == connection.execute(
            text("SELECT id, full_name, mobile, version FROM candidates ORDER BY id")
        ).all()
    )


def test_pages_profile_links_and_existing_fields(desk):
    client, _, _ = desk
    person = create(
        client,
        full_name="Lookup Person",
        mobile="9876543210",
        role_title="Synthetic Engineer",
        current_location="Synthetic City",
    )
    for path in ["/candidate-desk", "/candidates"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "data-candidate-lookup" in response.text
        assert "/static/candidates/lookup.mjs" in response.text
    response = client.get("/candidates?q=lookup", headers={"HX-Request": "true"})
    assert response.status_code == 200
    for value in [person["full_name"], person["mobile"], "Synthetic Engineer", "Synthetic City"]:
        assert value in response.text
    assert f'href="/candidates/{person["id"]}"' in response.text
    assert client.get(f"/candidates/{person['id']}").status_code == 200
    assert (
        "No matching candidates"
        in client.get("/candidates?q=missing", headers={"HX-Request": "true"}).text
    )

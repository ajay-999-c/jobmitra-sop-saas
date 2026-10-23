"""Quick entry persistence against the runner's disposable PostgreSQL only."""

import os
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_foundit_parser import QUICK_ENTRY_SAMPLE
from test_stage2 import database as database

from jobmitra.main import create_app
from jobmitra.modules.candidates.models import Candidate

pytestmark = pytest.mark.skipif(
    os.getenv("JOBMITRA_STAGE3_DISPOSABLE") != "1", reason="Disposable runner required"
)


def test_quick_entry_commits_survives_fresh_session_and_explicit_duplicate_choices(database):
    engine, settings, *_ = database
    assert settings.db_host.startswith("/private/tmp/jobmitra-stage2-")
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["X-Jobmitra-UI"] = "1"
        with engine.connect() as connection:
            before = {
                table: connection.scalar(text(f"SELECT count(*) FROM {table}"))
                for table in (
                    "candidate_visits",
                    "job_search_requests",
                    "candidate_documents",
                    "companies",
                )
            }
        preview = client.post("/api/candidates/foundit/preview", json={"raw": QUICK_ENTRY_SAMPLE})
        assert preview.status_code == 200
        payload = {
            key: value for key, value in preview.json()["fields"].items() if value is not None
        }
        payload.update(
            confirmed=True, domain_id=None, subdomain_id=None, role_title="Reviewed Engineer"
        )
        # No staff selection required for ordinary registration. The API still requires intent.
        assert (
            client.post(
                "/api/candidates/foundit/confirm", json={**payload, "confirmed": False}
            ).status_code
            == 422
        )
        invalid = client.post(
            "/api/candidates/foundit/confirm", json={**payload, "email": "invalid"}
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"][0]["loc"] == ["body", "email"]
        created = client.post("/api/candidates/foundit/confirm", json=payload)
        assert created.status_code == 201, created.text
        candidate = created.json()
        identity = UUID(candidate["id"])
        with Session(engine) as fresh:
            row = fresh.get(Candidate, identity)
            assert row.full_name == "Synthetic Parser Candidate"
            assert row.experience_months == 28 and row.current_salary_amount == 350000
            assert row.current_salary_period == "Unknown"
            assert row.domain_id is row.subdomain_id is None
            assert row.role_title == "Reviewed Engineer"
        assert (
            client.get("/candidates", params={"q": "Synthetic Parser Candidate"}).status_code == 200
        )
        assert "Synthetic Parser Candidate" in client.get("/candidates").text
        assert client.get("/candidates/" + candidate["id"]).status_code == 200
        assert client.post("/api/candidates/foundit/confirm", json=payload).status_code == 409
        duplicates = client.get(
            "/api/candidates/duplicates", params={"mobile": payload["mobile"]}
        ).json()
        assert candidate["id"] in [item["id"] for item in duplicates]
        patch = {
            "confirmed": True,
            "version": candidate["version"],
            "role_title": "Confirmed Lean Engineer",
        }
        updated = client.patch(f"/api/candidates/foundit/{identity}/confirm", json=patch)
        assert updated.status_code == 200, updated.text
        for key in candidate.keys() - {"role_title", "version", "updated_at"}:
            if key.endswith("salary_amount") and candidate[key] is not None:
                assert Decimal(updated.json()[key]) == Decimal(candidate[key])
            else:
                assert updated.json()[key] == candidate[key]
        assert (
            client.patch(f"/api/candidates/foundit/{identity}/confirm", json=patch).status_code
            == 409
        )
        # Explicit separate-person confirmation is the only duplicate creation override.
        separate = client.post(
            "/api/candidates/foundit/confirm",
            json={**payload, "full_name": "Separate Synthetic Person", "confirm_duplicate": True},
        )
        assert separate.status_code == 201
        # Shared existing contacts must not block a selected role-only edit.
        changed = client.patch(
            f"/api/candidates/foundit/{identity}/confirm",
            json={**patch, "version": updated.json()["version"], "role_title": "Engineer II"},
        )
        assert changed.status_code == 200, changed.text
        with Session(engine) as fresh:
            assert (
                len(
                    fresh.scalars(
                        select(Candidate).where(Candidate.mobile == payload["mobile"])
                    ).all()
                )
                == 2
            )
        with engine.connect() as connection:
            assert before == {
                table: connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in before
            }
    # A new application/client and a separate transaction still see the committed candidate.
    with TestClient(create_app(settings)) as fresh_client:
        loaded = fresh_client.get(f"/api/candidates/{identity}")
        assert loaded.status_code == 200
        assert loaded.json()["role_title"] == "Engineer II"

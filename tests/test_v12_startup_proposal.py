"""Targeted V12 startup/proposal tests; all data is synthetic and isolated."""

import hashlib
import json
import sqlite3
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_approved_v12 import client as client
from test_unified_v12 import snapshot
from test_unified_v12 import store as store
from test_unified_v12 import v2 as v2

from jobmitra.core import local_v12
from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import proposal
from jobmitra.modules.ats_v2.database import transaction
from jobmitra.modules.email_studio.router import PROPOSAL_FILE


def config(path, enabled=True):
    return Settings(
        _env_file=None,
        db_host="127.0.0.1",
        db_port=9,
        db_name="unused",
        db_user="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=path,
        unified_v12_enabled=enabled,
    )


def copy_database(source, target):
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as old:
        with sqlite3.connect(target) as new:
            old.backup(new)


def test_v12_root_overview_and_all_direct_workspaces_without_postgres(client, store):
    before = snapshot(store[0])
    for route in ["/", "/overview"]:
        response = client.get(route, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/workspace-v12/companies"
    for section in ["companies", "candidates", "jobs", "email"]:
        response = client.get("/workspace-v12/" + section)
        assert response.status_code == 200
        assert f'data-section="{section}"' in response.text
        assert "/static/ats-v2/approved.mjs" in response.text
    assert client.get("/email/proposal").content == PROPOSAL_FILE.read_bytes()
    assert client.get("/api/ats-v2/candidates").status_code == 200
    assert snapshot(store[0]) == before


def test_default_mode_keeps_legacy_root_and_disables_v12(store):
    pg = Mock()
    pg.connect.side_effect = AssertionError("No PostgreSQL access")
    with (
        patch("jobmitra.main.build_engine", return_value=pg),
        TestClient(create_app(config(store[-1] / "isolated.sqlite3", False))) as c,
    ):
        response = c.get("/", follow_redirects=False)
        assert response.headers["location"] == "/overview"
        assert c.get("/workspace-v12/companies").status_code == 404
    pg.connect.assert_not_called()


def test_v12_incompatible_v2_never_migrates_or_falls_back(v2):
    before = snapshot(v2[0])
    pg = Mock()
    pg.connect.side_effect = AssertionError("No PostgreSQL access")
    with (
        patch("jobmitra.main.build_engine", return_value=pg),
        TestClient(create_app(config(v2[-1] / "isolated.sqlite3"))) as c,
    ):
        for route in ["/", "/overview"]:
            response = c.get(route, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/workspace-v12/companies"
        for section in ["companies", "candidates", "jobs", "email"]:
            assert c.get("/workspace-v12/" + section).status_code == 503
    assert snapshot(v2[0]) == before
    pg.connect.assert_not_called()


def test_local_profile_uses_only_existing_isolated_v3_and_ignores_live_paths(
    store, monkeypatch, tmp_path
):
    root = tmp_path / "v12-local"
    root.mkdir()
    path = root / "ats-v3.sqlite3"
    copy_database(store[-1] / "isolated.sqlite3", path)
    monkeypatch.setattr(local_v12, "LOCAL_ROOT", root)
    monkeypatch.setenv("JOBMITRA_ATS_V2_DATABASE", "/forbidden-production.sqlite3")
    monkeypatch.setenv("JOBMITRA_DB_HOST", "forbidden-production.example")
    before = path.read_bytes()
    settings = local_v12.local_settings()
    assert settings.ats_v2_database == path
    assert settings.db_host == "127.0.0.1" and settings.db_port == 9
    assert settings.unified_v12_enabled and settings.ats_v2_enabled
    assert not settings.resume_processing_enabled
    assert settings.unified_v12_operator_token is None
    assert path.read_bytes() == before


def test_local_profile_refuses_v2_missing_and_symlink_without_writes(v2, monkeypatch, tmp_path):
    root = tmp_path / "v12-local"
    root.mkdir()
    path = root / "ats-v3.sqlite3"
    monkeypatch.setattr(local_v12, "LOCAL_ROOT", root)
    with pytest.raises(RuntimeError, match="existing isolated"):
        local_v12.local_settings()
    assert not path.exists()
    copy_database(v2[-1] / "isolated.sqlite3", path)
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="SQLite V3"):
        local_v12.local_settings()
    assert path.read_bytes() == before
    path.unlink()
    path.symlink_to(v2[-1] / "isolated.sqlite3")
    with pytest.raises(RuntimeError, match="existing isolated"):
        local_v12.local_settings()


def test_proposal_context_and_studio_are_read_only_preserve_original_composers(client, store):
    company_id, contact_id = store[1:3]
    before = snapshot(store[0])
    with store[0].connect() as c:
        audits = c.scalar(text("SELECT count(*) FROM company_audit_events"))
    path = f"/api/v12/approved/companies/{company_id}"
    response = client.get(path + "/proposal-context")
    assert response.status_code == 200
    context = response.json()
    assert context["company_id"] == company_id
    assert context["company_contact_id"] == contact_id
    assert context["company_name"] == "Synthetic Client Company"
    assert context["recipient_email"] == ""  # Never invent an address.
    assert not context["history_available"] and context["history"] == []
    assert not context["delivery_enabled"]
    source = proposal.STUDIO_FILE.read_bytes()
    assert client.get(path + "/proposal-studio").content == source
    assert (
        hashlib.sha256(source).hexdigest()
        == "cb3f47308cb7dac56c48fef38be958a145e9db5faa96575226668767b4b56d40"
    )
    assert b"21 days' salary" in source and b"30 days' salary" in source
    assert b'value="6"' in source and b'value="8.33"' in source
    assert client.get("/email/proposal").content == PROPOSAL_FILE.read_bytes()
    assert snapshot(store[0]) == before
    with store[0].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM company_audit_events")) == audits
    assert client.post(path + "/proposal-context").status_code == 405


def test_proposal_contacts_cannot_cross_companies_and_archived_contacts_are_not_used(client, store):
    engine, company_id, contact_id, *_ = store
    other_id, other_contact = str(uuid4()), str(uuid4())
    with transaction(engine) as c:
        contacts = [
            {
                "id": other_contact,
                "contact_name": "Other HR",
                "email": "other@example.test",
                "is_primary_email": True,
            }
        ]
        c.execute(
            text(
                "INSERT INTO companies(id,company_name,company_name_key,contacts_json) "
                "VALUES(:id,'Other Synthetic Company','other synthetic company',:contacts)"
            ),
            {"id": other_id, "contacts": json.dumps(contacts)},
        )
        c.execute(
            text("UPDATE companies SET contacts_json=:contacts WHERE id=:id"),
            {
                "id": company_id,
                "contacts": json.dumps(
                    [
                        {
                            "id": contact_id,
                            "contact_name": "Primary HR",
                            "email": "primary@example.test",
                            "is_primary_email": True,
                        }
                    ]
                ),
            },
        )
    own = f"/api/v12/approved/companies/{company_id}"
    other = f"/api/v12/approved/companies/{other_id}"
    assert client.get(own + "/proposal-context").json()["recipient_email"] == "primary@example.test"
    assert client.get(other + "/proposal-context").json()["recipient_email"] == "other@example.test"
    for route in ["/proposal-context", "/proposal-studio"]:
        assert (
            client.get(own + route, params={"company_contact_id": other_contact}).status_code == 422
        )
        assert (
            client.get(other + route, params={"company_contact_id": contact_id}).status_code == 422
        )
    with transaction(engine) as c:
        c.execute(
            text("UPDATE companies SET contacts_json=:contacts WHERE id=:id"),
            {
                "id": company_id,
                "contacts": json.dumps(
                    [
                        {
                            "id": contact_id,
                            "email": "archived@example.test",
                            "is_archived": True,
                            "is_primary_email": True,
                        }
                    ]
                ),
            },
        )
    context = client.get(own + "/proposal-context").json()
    assert context["contacts"] == [] and context["recipient_email"] == ""
    assert context["company_contact_id"] is None
    assert (
        client.get(own + "/proposal-context", params={"company_contact_id": contact_id}).status_code
        == 422
    )
    assert client.get(f"/api/v12/approved/companies/{uuid4()}/proposal-context").status_code == 404

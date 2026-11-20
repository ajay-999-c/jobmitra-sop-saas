"""Only the local editing boundary; synthetic SQLite, no PostgreSQL connection."""

import sqlite3
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pdf_fixture import valid_pdf
from test_unified_v12 import store as store
from test_unified_v12 import v2 as v2

from jobmitra.core import local_v12
from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import profile_store


@pytest.fixture
def preview(store, monkeypatch):
    profile_store.install(store[0])
    root = store[-1] / "runtime"
    root.mkdir()
    path = root / "preview.sqlite3"
    with sqlite3.connect(store[-1] / "isolated.sqlite3") as old, sqlite3.connect(path) as new:
        old.backup(new)
    monkeypatch.setattr(local_v12, "PROJECT_ENV_FILE", store[-1] / ".env")
    monkeypatch.delenv("UVICORN_HOST", raising=False)
    settings = Settings(
        _env_file=None,
        db_host="127.0.0.1",
        db_port=9,
        db_name="unused",
        db_user="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=path,
        ats_v2_resume_storage_root=root / "resumes",
        unified_v12_enabled=True,
        unified_v12_local_direct_editing=True,
    )
    with patch("jobmitra.main.build_engine", return_value=Mock()):
        yield settings, store[3]


def client(settings, **kwargs):
    return TestClient(
        create_app(settings), base_url="http://127.0.0.1", client=("127.0.0.1", 5000), **kwargs
    )


def headers():
    return {"X-Jobmitra-UI": "1", "Origin": "http://127.0.0.1", "Idempotency-Key": str(uuid4())}


def test_local_edit_and_resume_without_cookie_keep_validation_and_stale_checks(preview):
    settings, cid = preview
    with client(settings) as c:
        session = c.get("/api/v12/access").json()
        assert session == {
            "editing": True,
            "role": "LOCAL_DEVELOPMENT",
            "local_development": True,
            "actor_name": local_v12.LOCAL_ACTOR,
        }
        path = f"/api/v12/approved/candidates/{cid}/profile"
        before = c.get(path).json()
        body = {
            "changes": {"job_title": "Direct development edit"},
            "extra": {},
            "approved_fields": ["job_title"],
            "expected_revision": before["revision"],
            "actor_name": session["actor_name"],
            "idempotency_key": str(uuid4()),
        }
        assert c.patch(path, json=body, headers=headers()).status_code == 200
        assert c.get(path).json()["candidate"]["job_title"] == "Direct development edit"
        body["idempotency_key"] = str(uuid4())
        assert c.patch(path, json=body, headers=headers()).status_code == 409
        body["expected_revision"] = c.get(path).json()["revision"]
        assert c.patch(path, json=body, headers={"X-Jobmitra-UI": "1"}).status_code == 422
        bad_origin = headers() | {"Origin": "http://external.example"}
        assert c.patch(path, json=body, headers=bad_origin).status_code == 403
        response = c.post(
            f"/api/ats-v2/candidates/{cid}/resumes",
            content=valid_pdf(),
            headers=headers() | {"X-Resume-Filename": "synthetic.pdf"},
        )
        assert response.status_code == 201, response.text
        assert not c.cookies


def test_normal_configuration_still_rejects_unauthenticated_writes(preview):
    settings, cid = preview
    protected = settings.model_copy(update={"unified_v12_local_direct_editing": False})
    with client(protected) as c:
        assert c.get("/api/v12/access").json()["editing"] is False
        for method, path in [
            ("PATCH", f"/api/v12/approved/candidates/{cid}/profile"),
            ("POST", "/api/v12/companies"),
            ("POST", "/api/ats-v2/jobs"),
            ("POST", f"/api/ats-v2/candidates/{cid}/resumes"),
        ]:
            assert c.request(method, path, json={}, headers=headers()).status_code == 403


def test_local_mode_rejects_lan_host_peer_server_and_forwarding(preview):
    settings, _ = preview
    with client(settings) as c:
        for extra in [
            {"Host": "192.168.1.2"},
            {"Host": "external.example"},
            {"X-Forwarded-For": "127.0.0.1"},
            {"Forwarded": "for=127.0.0.1"},
        ]:
            assert c.get("/api/v12/access", headers=extra).status_code == 403
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1", client=("192.168.1.3", 5000)
    ) as c:
        assert c.get("/api/v12/access").status_code == 403
    with TestClient(
        create_app(settings), base_url="http://0.0.0.0", client=("127.0.0.1", 5000)
    ) as c:
        assert c.get("/api/v12/access", headers={"Host": "127.0.0.1"}).status_code == 403


def test_local_configuration_fails_closed_outside_runtime_and_nonloopback_bind(
    preview, monkeypatch
):
    settings, _ = preview
    wrong = settings.model_copy(
        update={"ats_v2_database": settings.ats_v2_database.parent.parent / "isolated.sqlite3"}
    )
    with pytest.raises(RuntimeError, match="isolated"):
        create_app(wrong)
    monkeypatch.setattr("sys.argv", ["uvicorn", "jobmitra.main:app", "--host", "0.0.0.0"])
    with pytest.raises(RuntimeError, match="non-loopback"):
        create_app(settings)

"""Workspace checksum portability and opt-in read-only office startup checks."""

import hashlib
import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from jobmitra.modules.ats_v2 import workspace_store

STORED_LF_SHA256 = "e1acaa21f455ef40b36da87aa9cab794130514caf93d9a01cda0a60bb0835d59"
SQL_LF = workspace_store.SQL_PATH.read_bytes().replace(b"\r\n", b"\n")


@pytest.mark.parametrize("endings", ["LF", "CRLF", "MIXED"])
def test_line_endings_preserve_existing_manifest(tmp_path, monkeypatch, endings):
    assert hashlib.sha256(SQL_LF).hexdigest() == STORED_LF_SHA256
    data = SQL_LF
    if endings == "CRLF":
        data = data.replace(b"\n", b"\r\n")
    elif endings == "MIXED":
        data = data.replace(b"\n", b"\r\n", 1)
    path = tmp_path / "workspace.sql"
    path.write_bytes(data)
    monkeypatch.setattr(workspace_store, "SQL_PATH", path)
    assert workspace_store.digest() == STORED_LF_SHA256


@pytest.mark.parametrize(
    "modified",
    [
        SQL_LF.replace(b"ON DELETE RESTRICT", b"ON DELETE CASCADE"),
        SQL_LF.replace(b"CREATE TABLE", b"CREATE  TABLE", 1),
        SQL_LF + b"-- changed SQL definition\n",
        SQL_LF + b"\r",
    ],
    ids=["foreign-key-rule", "sql-whitespace", "comment", "lone-carriage-return"],
)
def test_content_changes_are_not_normalized_away(tmp_path, monkeypatch, modified):
    path = tmp_path / "workspace.sql"
    path.write_bytes(modified.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(workspace_store, "SQL_PATH", path)
    assert workspace_store.digest() != STORED_LF_SHA256


@pytest.fixture
def office_settings():
    if os.environ.get("JOBMITRA_OFFICE_MANIFEST_READONLY_TESTS") != "1":
        pytest.skip("Explicit read-only office manifest verification opt-in required")
    from jobmitra.core.config import PROJECT_ENV_FILE, Settings

    settings = Settings(
        _env_file=[PROJECT_ENV_FILE, PROJECT_ENV_FILE.with_name(".env.v12.mac.postgres")]
    )
    assert (
        settings.v12_backend,
        settings.db_host,
        settings.db_port,
        settings.db_name,
        settings.db_user,
        settings.v12_postgres_schema,
    ) == (
        "postgresql",
        "192.168.1.51",
        5432,
        "jobmitra_dev",
        "jobmitra_app",
        "jobmitra_v12_dev_20261123_integration",
    )
    return settings.model_copy(update={"gmail_enabled": False})


@contextmanager
def readonly_office_client(settings):
    from fastapi.testclient import TestClient

    def readonly(dialect, record, args, params):
        params["options"] = params.get("options", "") + " -c default_transaction_read_only=on"

    event.listen(Engine, "do_connect", readonly)
    try:
        with patch("jobmitra.core.config.get_settings", return_value=settings):
            from jobmitra.main import create_app

            app = create_app(settings)
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5100)) as client:
            yield client, app
    finally:
        event.remove(Engine, "do_connect", readonly)


@pytest.mark.integration
@pytest.mark.parametrize("endings", ["LF", "CRLF"])
def test_office_startup_accepts_both_line_endings(office_settings, tmp_path, monkeypatch, endings):
    from sqlalchemy import text

    sql = tmp_path / "workspace.sql"
    sql.write_bytes(SQL_LF if endings == "LF" else SQL_LF.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(workspace_store, "SQL_PATH", sql)
    with readonly_office_client(office_settings) as (client, app):
        engine = app.state.ats_v2_engine
        assert engine._v12_schema == office_settings.v12_postgres_schema
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT current_database()")) == "jobmitra_dev"
            assert conn.scalar(text("SHOW default_transaction_read_only")) == "on"
            before = conn.execute(text("SELECT * FROM jd_workspace_versions")).all()
        assert before == [(1, STORED_LF_SHA256, "public")]
        for path in (
            "/health/ready",
            "/api/ats-v2/health",
            "/workspace-v12/jobs",
            "/workspace-v12/employees",
            "/api/v12/approved/jd-dashboard",
            "/api/v12/employees",
            "/api/v12/approved/candidate-directory",
        ):
            assert client.get(path).status_code == 200
        with engine.connect() as conn:
            assert conn.execute(text("SELECT * FROM jd_workspace_versions")).all() == before


@pytest.mark.integration
def test_office_startup_rejects_changed_sql(office_settings, tmp_path, monkeypatch):
    sql = tmp_path / "workspace.sql"
    sql.write_bytes(
        SQL_LF.replace(b"ON DELETE RESTRICT", b"ON DELETE CASCADE").replace(b"\n", b"\r\n")
    )
    monkeypatch.setattr(workspace_store, "SQL_PATH", sql)
    with (
        pytest.raises(RuntimeError, match=r"JD workspace extension manifest mismatch\."),
        readonly_office_client(office_settings),
    ):
        pytest.fail("Startup must reject changed SQL before serving requests")

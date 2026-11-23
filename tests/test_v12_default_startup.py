"""Only default startup/navigation and copy-only Windows local setup."""

import importlib.util
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from test_approved_v12 import client as client
from test_unified_v12 import store as store
from test_unified_v12 import v2 as v2

from jobmitra.core import config, local_v12


@pytest.fixture(autouse=True)
def reset_cached_settings():
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.mark.parametrize(
    "launcher",
    [
        "uvicorn",
        "/venv/bin/uvicorn",
        "/venv/lib/python3.12/site-packages/uvicorn/__main__.py",
        r"C:\Jobmitra\.venv\Scripts\uvicorn.exe",
        r"C:\Jobmitra\.venv\Lib\site-packages\uvicorn\__main__.py",
    ],
)
def test_exact_source_checkout_loopback_command_selects_local_v12(launcher, monkeypatch):
    monkeypatch.delenv("JOBMITRA_LOCAL_V12", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            launcher,
            "jobmitra.main:app",
            "--app-dir",
            "src",
            "--host",
            "127.0.0.1",
            "--port",
            "8002",
            "--workers",
            "1",
        ],
    )
    expected = object()
    with patch.object(local_v12, "local_settings", return_value=expected) as local:
        assert config.get_settings() is expected
        local.assert_called_once_with()


@pytest.mark.parametrize(
    "args",
    [
        ["uvicorn", "jobmitra.main:app", "--host", "127.0.0.1"],
        ["uvicorn", "jobmitra.main:app", "--app-dir", "src", "--host", "0.0.0.0"],
        ["uvicorn", "jobmitra.main:app", "--app-dir", "src", "--host", "192.168.1.51"],
        ["uvicorn", "jobmitra.main:app", "--app-dir", "src"],
        ["uvicorn", "other.main:app", "--app-dir", "src", "--host", "127.0.0.1"],
        ["worker.py", "jobmitra.main:app", "--app-dir", "src", "--host", "127.0.0.1"],
    ],
)
def test_service_lan_or_other_commands_keep_normal_configuration(args, monkeypatch):
    monkeypatch.delenv("JOBMITRA_LOCAL_V12", raising=False)
    monkeypatch.delenv("UVICORN_HOST", raising=False)
    monkeypatch.setattr("sys.argv", args)
    expected = object()
    with patch.object(config, "Settings", return_value=expected):
        assert config.get_settings() is expected


def test_explicit_legacy_override_and_equal_flags(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["uvicorn", "jobmitra.main:app", "--app-dir=src", "--host=localhost", "--port=8002"],
    )
    assert local_v12.default_local_startup()
    monkeypatch.setenv("JOBMITRA_LOCAL_V12", "0")
    expected = object()
    with patch.object(config, "Settings", return_value=expected):
        assert config.get_settings() is expected


def test_dotenv_postgres_selection_precedes_automatic_sqlite_profile(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("JOBMITRA_V12_BACKEND=postgresql\n")
    monkeypatch.setattr(config, "PROJECT_ENV_FILE", env)
    monkeypatch.delenv("JOBMITRA_V12_BACKEND", raising=False)
    monkeypatch.setenv("JOBMITRA_LOCAL_V12", "0")
    expected = object()
    with (
        patch.object(config, "Settings", return_value=expected),
        patch.object(local_v12, "default_local_startup", return_value=True),
        patch.object(local_v12, "local_settings") as sqlite,
    ):
        assert config.get_settings() is expected
        sqlite.assert_not_called()


@pytest.mark.parametrize("backend,local", [("unknown", "0"), ("postgresql", "1")])
def test_invalid_or_conflicting_backend_selection_fails_closed(backend, local, monkeypatch):
    monkeypatch.setenv("JOBMITRA_V12_BACKEND", backend)
    monkeypatch.setenv("JOBMITRA_LOCAL_V12", local)
    with pytest.raises(RuntimeError), patch.object(local_v12, "local_settings") as sqlite:
        config.get_settings()
    sqlite.assert_not_called()


def test_missing_local_database_never_falls_back_or_creates_empty_file(tmp_path, monkeypatch):
    monkeypatch.delenv("JOBMITRA_LOCAL_V12", raising=False)
    monkeypatch.setattr(local_v12, "LOCAL_ROOT", tmp_path / "missing")
    monkeypatch.setattr(
        "sys.argv", ["uvicorn", "jobmitra.main:app", "--app-dir", "src", "--host", "127.0.0.1"]
    )
    with pytest.raises(RuntimeError, match="prepare_local_v12"):
        config.get_settings()
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    "path,target",
    [
        ("/", "companies"),
        ("/overview/", "companies"),
        ("/companies", "companies"),
        ("/candidate-desk", "candidates"),
        ("/candidate-search-v2/", "candidates"),
        ("/requirements", "jobs"),
        ("/jd-workspace-v2/", "jobs"),
    ],
)
def test_legacy_entry_points_redirect_to_approved_shell(client, path, target):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/workspace-v12/" + target
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert "/static/ats-v2/approved.mjs" in page.text
    assert "JD Workspace (New)" not in page.text and "Candidate Desk (New)" not in page.text


def load_setup():
    spec = importlib.util.spec_from_file_location(
        "prepare_local_v12", Path(__file__).parents[1] / "scripts/prepare_local_v12.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        return {
            name: sorted(map(repr, conn.execute('SELECT * FROM "' + name + '"').fetchall()))
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


@pytest.mark.parametrize("version", [2, 3])
def test_explicit_setup_copies_populated_data_and_documents_without_source_changes(
    v2, tmp_path, monkeypatch, version
):
    module = load_setup()
    monkeypatch.setattr(config, "PROJECT_ENV_FILE", tmp_path / ".env")
    source = tmp_path / "isolated.sqlite3"
    if version == 3:
        from jobmitra.modules.ats_v2.database import upgrade_unified

        upgrade_unified(v2[0])
    source_files = tmp_path / "original-resumes"
    source_files.mkdir(mode=0o700)
    (source_files / "synthetic-resume.pdf").write_bytes(b"%PDF-synthetic immutable source")
    before = rows(source)
    target = tmp_path / "runtime" / "v12-local"
    result = module.prepare(
        source,
        {"resumes": source_files, "proposal-documents": None, "legacy-documents": None},
        target,
    )
    assert result["source_version"] == version and result["version"] == 3
    assert rows(source) == before
    assert (target / "resumes/synthetic-resume.pdf").read_bytes() == (
        source_files / "synthetic-resume.pdf"
    ).read_bytes()
    assert not (target / ".preparing").exists()
    with sqlite3.connect(target / "ats-v3.sqlite3") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT count(*) FROM candidates").fetchone()[0] == 1
    with pytest.raises(RuntimeError, match="already exists"):
        module.prepare(source, {"resumes": source_files}, target)
    assert rows(source) == before


def test_incomplete_preparation_blocks_startup_and_missing_source_creates_nothing(
    tmp_path, monkeypatch
):
    module = load_setup()
    target = tmp_path / "runtime/v12-local"
    with pytest.raises(RuntimeError, match="actual existing populated"):
        module.prepare(tmp_path / "missing.sqlite3", {}, target)
    assert not target.exists()
    target.mkdir(parents=True)
    (target / ".preparing").write_text("Incomplete")
    monkeypatch.setattr(local_v12, "LOCAL_ROOT", target)
    with pytest.raises(RuntimeError, match="incomplete"):
        local_v12.local_settings()

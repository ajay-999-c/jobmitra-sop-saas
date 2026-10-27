"""Storage/config diagnostics only: temporary files and doubles, never a database."""

import json
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jobmitra.core.config import Settings, get_settings
from jobmitra.core.database import get_session
from jobmitra.core.workflow import WorkflowError
from jobmitra.modules.candidates import router, storage, storage_diagnostics


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    import os

    for key in list(os.environ):
        if key.upper().startswith("JOBMITRA_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(Settings.model_config, "env_file", tmp_path / ".env")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def settings(**kwargs):
    return Settings(
        db_host="unused",
        db_name="unused",
        db_user="unused",
        db_password="TEST-SECRET-MUST-NOT-BE-LOGGED",
        **kwargs,
    )


class WindowsDirectory(PureWindowsPath):
    """Windows path semantics with a fake D: directory; not Windows disk validation."""

    def is_dir(self):
        return str(self).lower() in {
            r"d:\jobmitradata\private-documents",
            r"d:\jobmitra data\private documents",
            r"\\server\share\private documents",
        }

    def is_symlink(self):
        return False

    def resolve(self):
        return self


@pytest.mark.parametrize(
    "root",
    [
        "D:/JobmitraData/private-documents",
        r"D:\JobmitraData\private-documents",
        r"D:\Jobmitra Data\private documents",
        r"\\server\share\private documents",
    ],
)
def test_windows_absolute_root_is_accepted(monkeypatch, root):
    monkeypatch.setattr(storage, "Path", WindowsDirectory)
    assert storage.LocalDocumentStorage(root, 4096).root.is_absolute()


@pytest.mark.parametrize(
    "root",
    [
        "D:JobmitraData/private-documents",
        "/d/JobmitraData/private-documents",
        "/Users/mac/Documents/jobmitra/private-documents",
        '"D:/JobmitraData/private-documents"',
        " D:/JobmitraData/private-documents",
        "D:/static/private-documents",
        "D:/TEMPLATES/private-documents",
    ],
)
def test_windows_invalid_root_keeps_existing_guard(monkeypatch, root):
    monkeypatch.setattr(storage, "Path", WindowsDirectory)
    with pytest.raises(WorkflowError, match="absolute non-static"):
        storage.LocalDocumentStorage(root, 4096)


def test_trailing_space_is_directory_mismatch_not_absolute_path_failure(monkeypatch):
    monkeypatch.setattr(storage, "Path", WindowsDirectory)
    with pytest.raises(WorkflowError, match="storage is missing"):
        storage.LocalDocumentStorage("D:/JobmitraData/private-documents ", 4096)


def test_native_absolute_directory_and_missing_directory(tmp_path):
    assert storage.LocalDocumentStorage(tmp_path, 4096).root == tmp_path.resolve()
    with pytest.raises(WorkflowError, match="storage is missing"):
        storage.LocalDocumentStorage(tmp_path / "missing", 4096)


def test_native_symlink_and_static_directory_rejected(tmp_path):
    target = tmp_path / "private"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks requires OS privileges")
    with pytest.raises(WorkflowError, match="absolute non-static"):
        storage.LocalDocumentStorage(alias, 4096)
    static = tmp_path / "static"
    static.mkdir()
    with pytest.raises(WorkflowError, match="absolute non-static"):
        storage.LocalDocumentStorage(static, 4096)


def test_dotenv_quotes_are_removed_but_environment_quotes_are_literal(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        'JOBMITRA_DOCUMENT_STORAGE_ROOT="D:/JobmitraData/private-documents"\n'
    )
    assert settings().document_storage_root == Path("D:/JobmitraData/private-documents")
    monkeypatch.setenv("JOBMITRA_DOCUMENT_STORAGE_ROOT", '"D:/JobmitraData/private-documents"')
    assert str(settings().document_storage_root).startswith('"')
    assert not PureWindowsPath(str(settings().document_storage_root)).is_absolute()


def test_working_directory_and_process_environment_override(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(
        "JOBMITRA_DOCUMENT_STORAGE_ROOT=D:/JobmitraData/private-documents\n"
    )
    monkeypatch.setitem(Settings.model_config, "env_file", project / ".env")
    unrelated = tmp_path / "service working directory"
    unrelated.mkdir()
    (unrelated / ".env").write_text("JOBMITRA_DOCUMENT_STORAGE_ROOT=wrong-directory\n")
    monkeypatch.chdir(unrelated)
    assert settings().document_storage_root == Path("D:/JobmitraData/private-documents")
    monkeypatch.setenv("JOBMITRA_DOCUMENT_STORAGE_ROOT", "relative-old-service-value")
    assert settings().document_storage_root == Path("relative-old-service-value")


def test_cached_settings_do_not_reload_after_env_file_edit(tmp_path, monkeypatch):
    for key in ("HOST", "NAME", "USER", "PASSWORD"):
        monkeypatch.setenv("JOBMITRA_DB_" + key, "unused-test")
    env = tmp_path / ".env"
    env.write_text("JOBMITRA_DOCUMENT_STORAGE_ROOT=old-relative-value\n")
    cached = get_settings()
    env.write_text("JOBMITRA_DOCUMENT_STORAGE_ROOT=D:/JobmitraData/private-documents\n")
    assert get_settings() is cached
    assert cached.document_storage_root == Path("old-relative-value")
    assert Settings().document_storage_root == Path("D:/JobmitraData/private-documents")


def test_diagnostics_are_allowlisted_and_do_not_change_error(tmp_path, monkeypatch, caplog):
    (tmp_path / ".env").write_text("UNRELATED_TOKEN=TOKEN-MUST-NOT-BE-LOGGED\n")
    monkeypatch.setenv("UNRELATED_SECRET", "ENV-MUST-NOT-BE-LOGGED")
    config = settings(document_storage_root="relative")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=config)))
    with pytest.raises(WorkflowError, match="absolute non-static"):
        router.storage(request)
    assert "jobmitra_storage_diagnostic" not in caplog.text
    monkeypatch.setenv("JOBMITRA_STORAGE_DIAGNOSTICS", "1")
    with pytest.raises(WorkflowError, match="absolute non-static"):
        router.storage(request)
    assert "not_absolute" in caplog.text
    for secret in (
        "TEST-SECRET-MUST-NOT-BE-LOGGED",
        "TOKEN-MUST-NOT-BE-LOGGED",
        "ENV-MUST-NOT-BE-LOGGED",
    ):
        assert secret not in caplog.text
    report = storage_diagnostics.storage_report(config)
    assert report["effective_root"] == "relative"
    assert report["cwd"] == str(tmp_path)
    assert "db_password" not in json.dumps(report)


def test_diagnostic_failure_cannot_change_storage_result(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBMITRA_STORAGE_DIAGNOSTICS", "1")

    def unavailable(_):
        raise PermissionError("SECRET must not appear in log")

    monkeypatch.setattr(router, "storage_report", unavailable)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(settings=settings(document_storage_root=tmp_path))
        )
    )
    assert router.storage(request).root == tmp_path.resolve()


def test_url_shaped_misconfiguration_is_redacted():
    assert storage_diagnostics.display_path("postgresql://user:private@host/db") == (
        "<URL-shaped value redacted>"
    )
    assert storage_diagnostics.display_path(Path("postgresql://user:private@host/db")) == (
        "<URL-shaped value redacted>"
    )


def test_http_error_never_exposes_diagnostics(monkeypatch, caplog):
    monkeypatch.setenv("JOBMITRA_STORAGE_DIAGNOSTICS", "1")
    app = FastAPI()
    app.state.settings = settings(document_storage_root="relative-private-root")
    app.include_router(router.router)

    def no_database():
        yield SimpleNamespace(rollback=lambda: None)

    app.dependency_overrides[get_session] = no_database
    zero = "00000000-0000-0000-0000-000000000000"
    with TestClient(app) as client:
        response = client.get(f"/candidates/{zero}/documents/{zero}/download")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Private storage must be an absolute non-static directory."
    }
    assert "relative-private-root" in caplog.text
    assert "relative-private-root" not in response.text


def test_default_dotenv_is_anchored_to_checkout():
    from jobmitra.core.config import PROJECT_ENV_FILE

    assert PROJECT_ENV_FILE.is_absolute()
    assert PROJECT_ENV_FILE == Path(__file__).resolve().parents[1] / ".env"


def test_dotenv_private_directory_with_spaces_saves_exact_original(tmp_path, monkeypatch):
    import io

    root = tmp_path / "private documents"
    root.mkdir()
    env = tmp_path / ".env"
    env.write_text(f'JOBMITRA_DOCUMENT_STORAGE_ROOT="{root.as_posix()}"\n')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config = settings()
    store = storage.LocalDocumentStorage(config.document_storage_root, config.resume_max_bytes)
    data = b"%PDF-1.4\nsynthetic test\n%%EOF\n"
    saved = store.save(io.BytesIO(data), "synthetic original.pdf")
    assert store.path(saved.storage_key).parent == root.resolve()
    assert store.path(saved.storage_key).read_bytes() == data
    assert list(elsewhere.iterdir()) == []


def test_inaccessible_storage_returns_sanitized_error(tmp_path, monkeypatch):
    config = settings(document_storage_root=tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=config)))

    def denied(*args):
        raise PermissionError("synthetic private path must not leak")

    monkeypatch.setattr(storage.Path, "is_dir", denied)
    with pytest.raises(WorkflowError, match="Private document storage is unavailable"):
        router.storage(request)

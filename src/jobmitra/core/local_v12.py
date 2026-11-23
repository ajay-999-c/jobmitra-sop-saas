"""Explicit local-only profile; never creates, upgrades or selects a production database."""

import ipaddress
import os
import sqlite3
import sys
from pathlib import Path

from starlette.datastructures import URL
from starlette.responses import JSONResponse

from .config import PROJECT_ENV_FILE, Settings

LOCAL_ROOT = PROJECT_ENV_FILE.parent / "runtime" / "v12-local"
LOCAL_ACTOR = "Local development user (unverified)"


def default_local_startup():
    """Recognize the source-checkout Uvicorn command with an explicit loopback bind."""
    program = sys.argv[0].replace("\\", "/").lower()
    if (
        not (
            program.rsplit("/", 1)[-1] in {"uvicorn", "uvicorn.exe"}
            or program.endswith("/uvicorn/__main__.py")
        )
        or "jobmitra.main:app" not in sys.argv[1:]
    ):
        return False

    def option(name, default=None):
        value = default
        for index, arg in enumerate(sys.argv[1:], 1):
            if arg == name:
                value = sys.argv[index + 1] if index + 1 < len(sys.argv) else None
            elif arg.startswith(name + "="):
                value = arg.split("=", 1)[1]
        return value

    directory = option("--app-dir")
    host = option("--host", os.environ.get("UVICORN_HOST"))
    return bool(
        directory
        and host
        and loopback(host)
        and Path(directory.replace("\\", "/")).resolve() == PROJECT_ENV_FILE.parent / "src"
    )


def loopback(host):
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or bool(
            getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback
        )
    except ValueError:
        return False


def redirected(path):
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def validate_direct_editing(settings):
    """No implicit production/path fallback, migration, or network-wide access."""
    if not settings.unified_v12_local_direct_editing:
        return
    runtime = PROJECT_ENV_FILE.parent / "runtime"
    path = settings.ats_v2_database
    if not settings.unified_v12_enabled or not settings.ats_v2_enabled or path is None:
        raise RuntimeError("Direct editing requires the isolated local V12 preview.")
    path = path.expanduser().absolute()
    if (
        not path.resolve().is_relative_to(runtime.resolve())
        or not path.is_file()
        or any(redirected(part) for part in [path, *path.parents])
        or path.stat().st_nlink != 1
    ):
        raise RuntimeError(
            "Direct editing requires an existing isolated SQLite file under runtime/."
        )
    for storage in (
        settings.ats_v2_resume_storage_root,
        settings.unified_v12_proposal_storage_root,
        settings.document_storage_root,
    ):
        if storage is not None and not storage.expanduser().resolve().is_relative_to(
            runtime.resolve()
        ):
            raise RuntimeError("Direct editing requires isolated file storage under runtime/.")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        if (
            conn.execute("PRAGMA user_version").fetchone()[0] != 3
            or conn.execute("PRAGMA application_id").fetchone()[0] != 1246576980
        ):
            raise RuntimeError("Direct editing requires existing SQLite V3; no migration was run.")
    # Uvicorn CLI binding is known before startup; programmatic servers are also
    # guarded on every request using the actual peer and local socket addresses.
    host = os.environ.get("UVICORN_HOST", "127.0.0.1")
    for index, arg in enumerate(sys.argv):
        if arg == "--host" and index + 1 < len(sys.argv):
            host = sys.argv[index + 1]
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]
    if not loopback(host):
        raise RuntimeError("Local V12 direct editing refuses a non-loopback host.")


class LocalPreviewGuard:
    def __init__(self, app, settings):
        self.app, self.enabled = app, settings.unified_v12_local_direct_editing

    async def __call__(self, scope, receive, send):
        if self.enabled and scope["type"] == "http":
            headers = {k.lower() for k, _ in scope["headers"]}
            server, client = scope.get("server"), scope.get("client")
            try:
                host = URL(scope=scope).hostname
                allowed = (
                    server
                    and client
                    and loopback(server[0])
                    and loopback(client[0])
                    and loopback(host)
                    and not any(k == b"forwarded" or k.startswith(b"x-forwarded-") for k in headers)
                )
            except (ValueError, TypeError):
                allowed = False
            if not allowed:
                return await JSONResponse(
                    {"detail": "Local development preview requires direct loopback access."},
                    status_code=403,
                )(scope, receive, send)
        return await self.app(scope, receive, send)


def local_settings() -> Settings:
    path = LOCAL_ROOT / "ats-v3.sqlite3"
    if (LOCAL_ROOT / ".preparing").exists():
        raise RuntimeError(
            "Local V12 data preparation is incomplete; no production fallback was used."
        )
    if (
        not path.is_file()
        or path.stat().st_nlink != 1
        or any(redirected(part) for part in [path, *path.parents])
    ):
        raise RuntimeError(
            "Local V12 requires its existing isolated runtime/v12-local/ats-v3.sqlite3 copy. "
            "Prepare it with: uv run --no-sync python scripts/prepare_local_v12.py --from-config. "
            "This copies existing data; startup never creates an empty database "
            "or migrates production."
        )
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        if (
            conn.execute("PRAGMA user_version").fetchone()[0] != 3
            or conn.execute("PRAGMA application_id").fetchone()[0] != 1246576980
        ):
            raise RuntimeError("Local V12 requires SQLite V3. No migration was performed.")
    return Settings(
        _env_file=None,
        db_host="127.0.0.1",
        db_port=9,
        db_name="local_v12_unused",
        db_user="unused",
        db_password="unused",
        db_connect_timeout=1,
        ats_v2_enabled=True,
        ats_v2_database=path,
        ats_v2_resume_storage_root=LOCAL_ROOT / "resumes",
        document_storage_root=LOCAL_ROOT / "legacy-documents",
        unified_v12_enabled=True,
        unified_v12_local_direct_editing=True,
        unified_v12_proposals_enabled=True,
        unified_v12_proposal_storage_root=LOCAL_ROOT / "proposal-documents",
        resume_processing_enabled=False,
        ai_enabled=False,
    )

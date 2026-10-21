"""Report retries must retain the baseline and fail safely before connecting."""

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jobmitra.core.config import Settings

spec = importlib.util.spec_from_file_location(
    "stage2_preflight", Path(__file__).resolve().parents[1] / "scripts/stage2_preflight.py"
)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def test_retries_preserve_existing_reports_and_private_permissions(tmp_path):
    original = tmp_path / "baseline.json"
    original.write_text('{"status":"unavailable"}\n')
    first, stream = preflight.reserve_report(original)
    with stream:
        stream.write("first retry\n")
    second, stream = preflight.reserve_report(original)
    with stream:
        stream.write("second retry\n")
    assert len({original, first, second}) == 3
    assert original.read_text() == '{"status":"unavailable"}\n'
    assert first.read_text() == "first retry\n"
    assert second.read_text() == "second retry\n"
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert stat.S_IMODE(second.stat().st_mode) == 0o600


def test_output_failure_stops_before_database_connection(monkeypatch, capsys):
    def blocked_output(path):
        raise PermissionError("private directory")

    def forbidden_connection(**kwargs):
        pytest.fail("Database must not be queried when the report cannot be saved")

    monkeypatch.setattr(preflight, "reserve_report", blocked_output)
    monkeypatch.setattr(preflight.psycopg, "connect", forbidden_connection)
    monkeypatch.setattr(sys, "argv", ["stage2_preflight", "--output", "baseline.json"])
    with pytest.raises(SystemExit) as error:
        preflight.main()
    assert error.value.code == 2
    assert "Cannot create the private output report" in capsys.readouterr().err


def test_network_report_redacts_credentials_and_isolates_libpq_overrides(monkeypatch):
    secret = "test-only-sensitive-value"
    settings = Settings(
        _env_file=None, db_host="192.0.2.1", db_name="test", db_user="test", db_password=secret
    )
    monkeypatch.setenv("PGHOSTADDR", "198.51.100.1")
    monkeypatch.setattr(preflight.socket, "create_connection", MagicMock())
    monkeypatch.setattr(preflight.shutil, "which", lambda name: f"/bin/{name}")

    def run(command, **kwargs):
        assert secret not in repr(command)
        if command[0].endswith("psql"):
            assert kwargs["env"]["PGPASSWORD"] == secret
            assert "PGHOSTADDR" not in kwargs["env"]
            assert "default_transaction_read_only=on" in kwargs["env"]["PGOPTIONS"]
            assert command[-1] == "SELECT 1"
            return subprocess.CompletedProcess(
                command, 2, stdout="", stderr=f"password authentication failed; {secret}"
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(preflight.subprocess, "run", run)
    result = preflight.network_diagnostics(settings)
    assert result["python_tcp"]["status"] == "connected"
    assert result["nc"]["status"] == "connected"
    assert result["psql_explicit_settings"]["error_code"] == "authentication_failed"
    assert secret not in json.dumps(result)
    assert os.environ["PGHOSTADDR"] == "198.51.100.1"


def test_network_probe_timeout_has_no_raw_process_details(monkeypatch):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 15, stderr="sensitive-driver-output")

    monkeypatch.setattr(preflight.subprocess, "run", timeout)
    assert preflight.probe_client(["psql"], {}) == {
        "status": "unavailable",
        "error_code": "client_timeout",
    }

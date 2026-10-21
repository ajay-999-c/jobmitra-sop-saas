from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from jobmitra import cli
from jobmitra.core.config import Settings
from jobmitra.core.database import (
    benchmark_database,
    build_engine,
    check_database,
    get_session,
)
from jobmitra.main import create_app


def isolated_settings(**kwargs):
    values = {
        "db_host": "localhost",
        "db_name": "unit_test",
        "db_user": "unit_test",
        "db_password": "test_password",
    }
    values.update(kwargs)
    return Settings(_env_file=None, **values)


def mock_engine():
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.scalar.return_value = 1
    return engine, connection


def unavailable():
    return OperationalError("SELECT 1", {}, Exception("password=DO_NOT_EXPOSE"))


def test_password_is_masked_and_special_characters_are_preserved():
    settings = isolated_settings(db_password="a@b:%/word")
    assert settings.database_url.password == "a@b:%/word"
    assert "a@b:%/word" not in str(settings.database_url)
    assert "a@b:%/word" not in repr(settings)


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "JOBMITRA_DB_HOST=dotenv-host\nJOBMITRA_DB_NAME=unit_test\n"
        "JOBMITRA_DB_USER=unit_test\nJOBMITRA_DB_PASSWORD=test_password\n"
    )
    monkeypatch.setenv("JOBMITRA_DB_HOST", "environment-host")
    assert Settings(_env_file=env_file).db_host == "environment-host"


def test_pool_and_timeouts():
    engine = build_engine(isolated_settings())
    try:
        assert engine.pool.size() == 3
        assert engine.pool._max_overflow == 0
        assert engine.pool._pre_ping is True
        assert engine.hide_parameters is True
    finally:
        engine.dispose()


def test_successful_health_check_releases_connection():
    engine, connection = mock_engine()
    assert check_database(engine) >= 0
    assert str(connection.scalar.call_args.args[0]) == "SELECT 1"
    engine.connect.return_value.__exit__.assert_called_once()


def test_unavailable_database_releases_connection():
    engine, connection = mock_engine()
    connection.scalar.side_effect = unavailable()
    with pytest.raises(OperationalError):
        check_database(engine)
    engine.connect.return_value.__exit__.assert_called_once()


def test_benchmark_runs_warmup_and_requested_queries():
    engine, connection = mock_engine()
    samples = benchmark_database(engine, 10)
    assert len(samples) == 10
    assert all(sample >= 0 for sample in samples)
    assert connection.scalar.call_count == 11
    assert all(str(call.args[0]) == "SELECT 1" for call in connection.scalar.call_args_list)
    engine.connect.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("iterations", [0, -1, 10001])
def test_benchmark_rejects_invalid_iterations(iterations):
    with pytest.raises(ValueError):
        benchmark_database(MagicMock(), iterations)


def test_benchmark_failure_releases_connection():
    engine, connection = mock_engine()
    connection.scalar.side_effect = [1, unavailable()]
    with pytest.raises(OperationalError):
        benchmark_database(engine, 10)
    engine.connect.return_value.__exit__.assert_called_once()


def test_unexpected_health_result_releases_connection():
    engine, connection = mock_engine()
    connection.scalar.return_value = 0
    with pytest.raises(RuntimeError):
        check_database(engine)
    engine.connect.return_value.__exit__.assert_called_once()


def test_cli_benchmark_summary(monkeypatch, capsys):
    import json

    engine, _ = mock_engine()
    monkeypatch.setattr("sys.argv", ["jobmitra-db", "benchmark", "--iterations", "3"])
    with (
        patch("jobmitra.cli.build_engine", return_value=engine),
        patch("jobmitra.cli.benchmark_database", return_value=[1.0, 2.0, 3.0]),
    ):
        assert cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["iterations"] == 3
    assert result["mean_ms"] == 2.0
    assert result["median_ms"] == 2.0
    assert result["p95_ms"] == 3.0
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("ai_enabled", [False, True])
def test_api_health_and_shutdown_without_ai_provider(ai_enabled):
    engine, _ = mock_engine()
    with patch("jobmitra.main.build_engine", return_value=engine):
        with TestClient(create_app(isolated_settings(ai_enabled=ai_enabled))) as client:
            assert client.get("/health/live").json() == {"status": "ok"}
            response = client.get("/health/ready")
            assert response.status_code == 200
            assert response.json()["database"] == "connected"
    engine.dispose.assert_called_once()


def test_api_database_unavailability_keeps_liveness_and_masks_error():
    engine, _ = mock_engine()
    engine.connect.side_effect = unavailable()
    with patch("jobmitra.main.build_engine", return_value=engine):
        with TestClient(create_app(isolated_settings())) as client:
            assert client.get("/health/live").status_code == 200
            response = client.get("/health/ready")
            assert response.status_code == 503
            assert response.json() == {"status": "unavailable"}
            assert "DO_NOT_EXPOSE" not in response.text
    engine.dispose.assert_called_once()


def test_session_dependency_closes_session():
    request = MagicMock()
    with patch("jobmitra.core.database.Session") as session_type:
        dependency = get_session(request)
        assert next(dependency) is session_type.return_value.__enter__.return_value
        dependency.close()
        session_type.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("fails", [False, True])
def test_cli_exit_code_cleanup_and_password_redaction(monkeypatch, capsys, fails):
    engine, _ = mock_engine()
    if fails:
        engine.connect.side_effect = unavailable()
    monkeypatch.setattr("sys.argv", ["jobmitra-db", "health"])
    with patch("jobmitra.cli.build_engine", return_value=engine):
        assert cli.main() == (1 if fails else 0)
    output = capsys.readouterr().out
    assert "DO_NOT_EXPOSE" not in output
    engine.dispose.assert_called_once()


def test_actual_refused_connection():
    # Reserve a TCP port without listening so it cannot be assigned to another process.
    import socket

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        engine = build_engine(
            isolated_settings(
                db_host="127.0.0.1", db_port=reserved.getsockname()[1], db_connect_timeout=1
            )
        )
        try:
            with pytest.raises(OperationalError):
                check_database(engine)
        finally:
            engine.dispose()


@pytest.mark.parametrize(
    ("driver_message", "expected_code"),
    [
        ("Operation not permitted", "network_permission_denied"),
        ("Permission denied", "network_permission_denied"),
        ("password authentication failed", "authentication_failed"),
        ("no password supplied", "authentication_failed"),
        ("no pg_hba.conf entry", "server_access_denied"),
        ("Connection refused", "connection_refused"),
        ("No route to host", "host_unreachable"),
        ("timeout expired", "network_unreachable_or_timeout"),
        ("Network is unreachable", "network_unreachable_or_timeout"),
        ("could not translate host name", "host_resolution_failed"),
        ("unexpected failure", "database_unavailable"),
    ],
)
def test_cli_failure_classification_never_returns_driver_text(driver_message, expected_code):
    import json

    secret = "sensitive@value:/password"
    error = OperationalError(
        "SELECT 1", {}, Exception(f"{driver_message}; password={secret}; private-driver-detail")
    )
    details = cli.database_failure_details(error)
    assert details["error_code"] == expected_code
    assert secret not in json.dumps(details)
    assert "private-driver-detail" not in json.dumps(details)


def test_cli_permission_failure_is_actionable_and_disposes_engine(monkeypatch, capsys):
    import json

    engine, _ = mock_engine()
    engine.connect.side_effect = OperationalError(
        "SELECT 1", {}, Exception("Operation not permitted; password=DO_NOT_EXPOSE")
    )
    monkeypatch.setattr("sys.argv", ["jobmitra-db", "health"])
    with patch("jobmitra.cli.build_engine", return_value=engine):
        assert cli.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output)["error_code"] == "network_permission_denied"
    assert "DO_NOT_EXPOSE" not in output
    engine.dispose.assert_called_once()

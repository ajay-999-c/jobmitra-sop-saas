"""Focused safety guards; these tests never open a database connection."""

import hashlib
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def migration(monkeypatch):
    monkeypatch.syspath_prepend(str(Path("scripts").resolve()))
    module = importlib.import_module("migrate_to_windows")

    def forbid_connection(**kwargs):
        pytest.fail("A rejected migration must not open a database connection")

    monkeypatch.setattr(module.psycopg, "connect", forbid_connection)
    monkeypatch.setattr(
        module,
        "Settings",
        lambda: SimpleNamespace(db_host="192.168.1.51", db_name="jobmitra_dev", db_port=5432),
    )
    return module


def test_archive_filter_preserves_all_table_entries_and_other_extensions(migration):
    catalog = (
        "; catalog\n"
        "2; 3079 1 EXTENSION - vector \n"
        "3; 0 0 COMMENT - EXTENSION vector \n"
        "4; 3079 2 EXTENSION - another_extension \n"
        "5; 1259 3 TABLE public companies jobmitra_app\n"
        "6; 0 3 TABLE DATA public companies jobmitra_app\n"
    )
    selected = migration.restore_list(catalog)
    assert "EXTENSION - vector" not in selected
    assert "EXTENSION vector" not in selected
    assert "EXTENSION - another_extension" in selected
    assert "TABLE public companies jobmitra_app" in selected
    assert "TABLE DATA public companies jobmitra_app" in selected


def test_unexpected_archive_extension_catalog_is_rejected(migration):
    with pytest.raises(migration.MigrationError):
        migration.restore_list("1; 1259 1 TABLE public companies jobmitra_app\n")


def test_wrong_destination_is_rejected_before_reading_backup(migration, monkeypatch, capsys):
    monkeypatch.setattr(
        migration,
        "Settings",
        lambda: SimpleNamespace(db_host="127.0.0.1", db_name="jobmitra_dev", db_port=5432),
    )
    monkeypatch.setattr(sys, "argv", ["migrate", "--backup", "not-used", "--apply"])
    assert migration.main() == 1
    assert "Expected target" in json.loads(capsys.readouterr().out)["message"]


def test_altered_backup_is_rejected_before_any_connection(migration, monkeypatch, tmp_path, capsys):
    archive = tmp_path / "jobmitra_dev.dump"
    archive.write_bytes(b"altered archive")
    manifest = {
        "status": "backup_verified",
        "source": {"host": "127.0.0.1", "port": 5432, "database": "jobmitra_dev"},
        "table_fingerprints": {name: {} for name in migration.TABLES},
        "archive": archive.name,
        "archive_sha256": hashlib.sha256(b"original archive").hexdigest(),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(sys, "argv", ["migrate", "--backup", str(tmp_path), "--apply"])
    assert migration.main() == 1
    assert "checksum mismatch" in json.loads(capsys.readouterr().out)["message"]


def test_private_reports_are_never_overwritten(migration, tmp_path):
    report = tmp_path / "report.json"
    migration.write_private(report, "original")
    with pytest.raises(FileExistsError):
        migration.write_private(report, "replacement")
    assert report.read_text() == "original"
    assert report.stat().st_mode & 0o777 == 0o600


@pytest.fixture
def login_setup(monkeypatch):
    monkeypatch.syspath_prepend(str(Path("scripts").resolve()))
    return importlib.import_module("create_windows_login")


class AdminDouble:
    def __init__(self, *, superuser=True, existing=False):
        self.superuser = superuser
        self.existing = existing
        self.statements = []
        self.pgconn = SimpleNamespace(encrypt_password=self.encrypt_password)

    def encrypt_password(self, password, user, algorithm):
        assert user == b"jobmitra_dev" and algorithm == b"scram-sha-256"
        return b"SCRAM-SHA-256$unit-test-verifier"

    def execute(self, query, parameters=None):
        rendered = query if isinstance(query, str) else query.as_string()
        self.statements.append(rendered)
        if "SELECT rolsuper" in rendered:
            return SimpleNamespace(fetchone=lambda: (self.superuser,))
        if "SELECT 1 FROM pg_roles" in rendered:
            return SimpleNamespace(fetchone=lambda: (1,) if self.existing else None)


def test_runtime_account_cannot_provision_a_login(login_setup):
    admin = AdminDouble(superuser=False)
    with pytest.raises(login_setup.SetupError):
        login_setup.provision(admin, "unit-test-secret")
    assert len(admin.statements) == 1


def test_existing_login_credentials_and_privileges_are_preserved(login_setup):
    admin = AdminDouble(existing=True)
    with pytest.raises(login_setup.SetupError):
        login_setup.provision(admin, "unit-test-secret")
    assert len(admin.statements) == 2
    assert all(statement.startswith("SELECT") for statement in admin.statements)


def test_new_login_uses_scram_without_plaintext_password_sql(login_setup):
    admin = AdminDouble()
    password = "unit-test-secret"
    login_setup.provision(admin, password)
    assert all(password not in statement for statement in admin.statements)
    create = next(
        statement for statement in admin.statements if statement.startswith("CREATE ROLE")
    )
    assert "SCRAM-SHA-256$unit-test-verifier" in create
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE" in create
    assert not any(
        statement.startswith(("UPDATE ", "DELETE ", "TRUNCATE ")) for statement in admin.statements
    )


def test_login_setup_rejects_other_servers_before_password_prompt(login_setup, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["create_windows_login"])
    monkeypatch.setattr(
        login_setup,
        "Settings",
        lambda: SimpleNamespace(db_host="127.0.0.1", db_name="jobmitra_dev", db_port=5432),
    )
    monkeypatch.setattr(
        login_setup.getpass, "getpass", lambda *args: pytest.fail("Unexpected password prompt")
    )
    assert login_setup.main() == 1
    assert "Expected Windows target" in json.loads(capsys.readouterr().out)["message"]

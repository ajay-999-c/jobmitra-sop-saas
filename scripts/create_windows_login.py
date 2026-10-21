"""Run in Terminal as a human: create the requested runtime login using an admin prompt."""

import argparse
import getpass
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from backup_database import connection_kwargs
from dotenv import set_key
from psycopg import sql

from jobmitra.cli import database_failure_details
from jobmitra.core.config import Settings

NEW_USER = "jobmitra_dev"


def require(condition, message):
    if not condition:
        raise SetupError(message)


class SetupError(Exception):
    """Static messages only; never include connection, SQL or password values."""


def provision(admin, app_password):
    """Administrator-owned transaction; no superuser privileges for the runtime login."""
    require(
        admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0],
        "Connect as a PostgreSQL administrator for login and extension setup",
    )
    require(
        not admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (NEW_USER,)).fetchone(),
        "Requested login already exists; its password and privileges were not changed",
    )
    # Like psql's \password, send a SCRAM verifier rather than a plaintext SQL password.
    verifier = admin.pgconn.encrypt_password(
        app_password.encode(), NEW_USER.encode(), b"scram-sha-256"
    ).decode()
    admin.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(sql.Identifier(NEW_USER), sql.Literal(verifier))
    )
    admin.execute("GRANT CONNECT ON DATABASE jobmitra_dev TO jobmitra_dev")
    admin.execute("GRANT USAGE ON SCHEMA public TO jobmitra_dev")
    admin.execute(
        "GRANT SELECT,INSERT,UPDATE,DELETE "
        "ON public.companies,public.company_contacts TO jobmitra_dev"
    )
    admin.execute("GRANT SELECT ON public.alembic_version TO jobmitra_dev")
    admin.execute("CREATE EXTENSION IF NOT EXISTS vector")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-user", default="postgres")
    args = parser.parse_args()
    committed = False
    try:
        settings = Settings()
        require(
            settings.db_host == "192.168.1.51"
            and settings.db_port == 5432
            and settings.db_name == "jobmitra_dev",
            "Expected Windows target 192.168.1.51:5432/jobmitra_dev",
        )
        require(
            bool(settings.db_password.get_secret_value()), "Set the app password in .env locally"
        )
        env_file = Path(".env")
        require(
            env_file.is_file() and not env_file.is_symlink(), "Run from the project root with .env"
        )
        original_env = env_file.read_bytes()
        require(
            sys.stdin.isatty(), "Run setup in an interactive Terminal with a hidden password prompt"
        )
        # The new app login uses the existing .env app password; it is never printed or replaced.
        admin_password = getpass.getpass("Windows PostgreSQL administrator password (hidden): ")
        admin_kwargs = connection_kwargs(settings, settings.db_host, user=args.admin_user)
        admin_kwargs["password"] = admin_password
        with psycopg.connect(**admin_kwargs) as admin:
            require(
                admin.execute("SELECT current_database()").fetchone()[0] == "jobmitra_dev",
                "Unexpected target database",
            )
            provision(admin, settings.db_password.get_secret_value())
        committed = True
        admin_kwargs.clear()
        admin_password = None
        with psycopg.connect(**connection_kwargs(settings, settings.db_host, user=NEW_USER)) as app:
            app.execute("SET TRANSACTION READ ONLY")
            for table in ("companies", "company_contacts"):
                require(
                    app.execute(
                        "SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE,DELETE')",
                        (table,),
                    ).fetchone()[0],
                    "Runtime login privilege verification failed",
                )
            require(
                app.execute("SELECT version_num FROM public.alembic_version").fetchone()[0]
                == "0001_company_management",
                "Unexpected schema revision",
            )
            vector = app.execute(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            ).fetchone()
            require(vector and vector[0] == "0.8.7", "Unexpected pgvector version")
        require(
            env_file.read_bytes() == original_env,
            ".env changed during setup; update its username locally",
        )
        set_key(env_file, "JOBMITRA_DB_USER", NEW_USER, quote_mode="never")
        env_file.chmod(0o600)
        result = {
            "status": "login_created_and_verified",
            "database": "jobmitra_dev",
            "host": "192.168.1.51",
            "user": NEW_USER,
            "runtime_superuser": False,
            "company_crud_granted": True,
            "pgvector_version": "0.8.7",
            "env_username_updated": True,
            "env_password_unchanged": True,
            "existing_login_preserved": True,
            "business_records_changed": False,
            "shell_override_present": "JOBMITRA_DB_USER" in os.environ,
        }
        folder = Path("outputs/windows-migration")
        folder.mkdir(parents=True, exist_ok=True)
        report = folder / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-login-setup.json")
        descriptor = os.open(report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        print(json.dumps({**result, "report": str(report)}))
        return 0
    except Exception as error:
        result = {"status": "setup_not_verified", "administrator_transaction_committed": committed}
        if isinstance(error, SetupError):
            result["message"] = str(error)
        else:
            result.update(database_failure_details(error))
        print(json.dumps(result))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

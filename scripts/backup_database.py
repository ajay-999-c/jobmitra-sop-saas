"""Read-only local backup before moving Jobmitra to the Windows PostgreSQL server."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

from jobmitra.cli import database_failure_details
from jobmitra.core.config import Settings

TABLES = ("alembic_version", "companies", "company_contacts")


def fingerprint(connection):
    """Stable hashes include every field, UUID and timestamp, without logging row values."""
    connection.execute("SET LOCAL TIME ZONE 'UTC'")
    result = {}
    for table in TABLES:
        rows = connection.execute(
            sql.SQL("SELECT to_jsonb(t) FROM public.{} AS t").format(sql.Identifier(table))
        ).fetchall()
        serialized = sorted(json.dumps(row[0], sort_keys=True, ensure_ascii=False) for row in rows)
        result[table] = {
            "rows": len(rows),
            "sha256": hashlib.sha256("\n".join(serialized).encode()).hexdigest(),
        }
    return result


def connection_kwargs(settings, host, *, user=None):
    return {
        "host": host,
        "port": settings.db_port,
        "dbname": settings.db_name,
        "user": user or settings.db_user,
        "password": settings.db_password.get_secret_value(),
        "connect_timeout": settings.db_connect_timeout,
        "sslmode": settings.db_sslmode,
        "application_name": "jobmitra-migration",
    }


def pg_environment(settings):
    # Ignore inherited libpq service/options variables; connection settings are explicit.
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(
        PGPASSWORD=settings.db_password.get_secret_value(),
        PGSSLMODE=settings.db_sslmode,
        PGCONNECT_TIMEOUT=str(settings.db_connect_timeout),
    )
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost", "::1"])
    parser.add_argument("--user", default="jobmitra_app", help="Original local source login")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = Settings()
    if settings.db_name != "jobmitra_dev":
        print(json.dumps({"status": "failed", "reason": "Expected source database jobmitra_dev"}))
        return 1
    pg_dump, pg_restore = shutil.which("pg_dump"), shutil.which("pg_restore")
    if not pg_dump or not pg_restore:
        print(json.dumps({"status": "failed", "reason": "PostgreSQL 18 client tools required"}))
        return 1
    output = args.output or Path("backups") / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        for executable in (pg_dump, pg_restore):
            version = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, check=True
            ).stdout
            if "(PostgreSQL) 18." not in version:
                raise RuntimeError("PostgreSQL 18 client tools required")
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        archive = output / "jobmitra_dev.dump"
        manifest_path = output / "manifest.json"
        with psycopg.connect(
            **connection_kwargs(settings, args.host, user=args.user)
        ) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            version = connection.execute("SHOW server_version").fetchone()[0]
            if connection.info.server_version // 10000 != 18:
                raise RuntimeError("PostgreSQL 18 source required")
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            if revision != "0001_company_management":
                raise RuntimeError("Unexpected source revision")
            before = fingerprint(connection)
            extensions = connection.execute(
                "SELECT extname, extversion FROM pg_extension ORDER BY extname"
            ).fetchall()
            snapshot = connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
            descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                process = subprocess.run(
                    [
                        pg_dump,
                        "--format=custom",
                        "--no-owner",
                        "--no-acl",
                        "--no-password",
                        f"--snapshot={snapshot}",
                        "--host",
                        args.host,
                        "--port",
                        str(settings.db_port),
                        "--username",
                        args.user,
                        "--dbname",
                        settings.db_name,
                    ],
                    stdout=stream,
                    stderr=subprocess.PIPE,
                    env=pg_environment(settings),
                    timeout=120,
                )
            if process.returncode:
                raise RuntimeError("Backup failed; archive must not be used")
        listing = subprocess.run(
            [pg_restore, "--list", str(archive)], capture_output=True, text=True, timeout=30
        )
        if listing.returncode or any(
            f"TABLE DATA public {table} " not in listing.stdout for table in TABLES
        ):
            raise RuntimeError("Backup archive catalog validation failed")
        manifest = {
            "status": "backup_verified",
            "created_at": datetime.now(UTC).isoformat(),
            "source": {"host": args.host, "port": settings.db_port, "database": settings.db_name},
            "server_version": version,
            "alembic_revision": revision,
            "extensions": [{"name": name, "version": version} for name, version in extensions],
            "table_fingerprints": before,
            "archive": archive.name,
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "archive_bytes": archive.stat().st_size,
            "snapshot_consistent": True,
            "restore_attempted": False,
        }
        descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
        print(
            json.dumps(
                {"status": "backup_verified", "manifest": str(manifest_path), "tables": before}
            )
        )
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "message": "Backup incomplete; do not restore it.",
                    **database_failure_details(error),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

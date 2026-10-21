"""Capture live metadata and company hashes using a database-enforced read-only transaction."""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

from jobmitra.cli import database_failure_details
from jobmitra.core.config import Settings


def network_diagnostics(settings):
    """Compare clients in one launch context, keeping credentials out of output."""
    result = {
        "libpq_environment_names": sorted(name for name in os.environ if name.startswith("PG")),
        "psycopg_implementation": psycopg.pq.__impl__,
        "libpq_version": psycopg.pq.version(),
    }
    try:
        with socket.create_connection(
            (settings.db_host, settings.db_port), timeout=settings.db_connect_timeout
        ):
            result["python_tcp"] = {"status": "connected"}
    except OSError as error:
        result["python_tcp"] = {
            "status": "unavailable",
            "errno": error.errno,
            **database_failure_details(error),
        }

    nc = shutil.which("nc")
    if nc:
        result["nc"] = probe_client(
            [
                nc,
                "-v",
                "-G",
                str(settings.db_connect_timeout),
                "-z",
                settings.db_host,
                str(settings.db_port),
            ],
            os.environ.copy(),
        )
    else:
        result["nc"] = {"status": "not_installed"}

    psql = shutil.which("psql")
    if psql:
        # Explicit application settings, independent of PGHOSTADDR/service overrides.
        # Password exists only in the child environment, never in argv or the report.
        env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        env.update(
            PGPASSWORD=settings.db_password.get_secret_value(),
            PGCONNECT_TIMEOUT=str(settings.db_connect_timeout),
            PGSSLMODE=settings.db_sslmode,
            PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=5000",
        )
        result["psql_explicit_settings"] = probe_client(
            [
                psql,
                "-X",
                "-w",
                "-h",
                settings.db_host,
                "-p",
                str(settings.db_port),
                "-U",
                settings.db_user,
                "-d",
                settings.db_name,
                "-tA",
                "-c",
                "SELECT 1",
            ],
            env,
        )
    else:
        result["psql_explicit_settings"] = {"status": "not_installed"}
    return result


def probe_client(command, env):
    try:
        process = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=15, check=False
        )
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "error_code": "client_timeout"}
    except OSError as error:
        return {"status": "unavailable", **database_failure_details(error)}
    if process.returncode == 0:
        return {"status": "connected"}
    return {
        "status": "unavailable",
        **database_failure_details(RuntimeError(process.stderr)),
    }


def reserve_report(path: Path):
    """Reserve a private report before connecting; retain every previous report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    attempt = 0
    while True:
        try:
            descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            return candidate, os.fdopen(descriptor, "w")
        except FileExistsError:
            attempt += 1
            candidate = path.with_name(f"{path.stem}-{stamp}-{attempt}{path.suffix}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--diagnose-network",
        action="store_true",
        help="Compare raw TCP, nc and psql without modifying PostgreSQL",
    )
    args = parser.parse_args()
    report_path, report = None, None
    if args.output:
        try:
            report_path, report = reserve_report(args.output)
        except OSError:
            parser.error(
                "Cannot create the private output report; check its directory permissions."
            )
    result = {"mode": "read_only", "captured_at": datetime.now(UTC).isoformat()}
    try:
        settings = Settings()
        result["target"] = {
            "host": settings.db_host,
            "port": settings.db_port,
            "database": settings.db_name,
            "user": settings.db_user,
        }
        if args.diagnose_network:
            result["network_diagnostics"] = network_diagnostics(settings)
        with psycopg.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password.get_secret_value(),
            sslmode=settings.db_sslmode,
            connect_timeout=settings.db_connect_timeout,
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
        ) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.execute("SET LOCAL TIME ZONE 'UTC'")
            assert connection.execute("SHOW transaction_read_only").fetchone()[0] == "on"
            result["server_version"] = connection.execute("SHOW server_version").fetchone()[0]
            result["revision"] = [
                row[0]
                for row in connection.execute("SELECT version_num FROM public.alembic_version")
            ]
            result["extensions"] = connection.execute(
                "SELECT extname,extversion FROM pg_extension ORDER BY extname"
            ).fetchall()
            result["tables"] = [
                row[0]
                for row in connection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
                )
            ]
            result["company_tables"] = {}
            for name in ("companies", "company_contacts"):
                rows = connection.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM public.{} t").format(sql.Identifier(name))
                ).fetchall()
                serialized = sorted(
                    json.dumps(row[0], sort_keys=True, ensure_ascii=False) for row in rows
                )
                result["company_tables"][name] = {
                    "count": len(rows),
                    "sha256": hashlib.sha256("\n".join(serialized).encode()).hexdigest(),
                }
            result["columns"] = connection.execute(
                "SELECT table_name,column_name,data_type,is_nullable,column_default "
                "FROM information_schema.columns WHERE table_schema='public' "
                "AND table_name IN ('companies','company_contacts') "
                "ORDER BY table_name,ordinal_position"
            ).fetchall()
            result["status"] = "captured"
    except Exception as error:
        details = database_failure_details(error)
        if "no route to host" in str(error).lower():
            details = {
                "error_code": "host_unreachable",
                "hint": "This execution session cannot reach the configured host.",
            }
        result.update(
            status="unavailable",
            exception_type=type(error).__name__,
            sqlstate=getattr(error, "sqlstate", None),
            **details,
        )
    if report is not None:
        with report as output:
            json.dump(result, output, indent=2, default=str)
            output.write("\n")
        print(f"Report saved: {report_path}")
    print(
        json.dumps({key: value for key, value in result.items() if key != "columns"}, default=str)
    )
    return 0 if result["status"] == "captured" else 1


if __name__ == "__main__":
    raise SystemExit(main())

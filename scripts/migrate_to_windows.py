"""Restore a verified local Jobmitra backup into an empty Windows database."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from backup_database import TABLES, connection_kwargs, fingerprint, pg_environment

from jobmitra.cli import database_failure_details
from jobmitra.core.config import Settings


class MigrationError(Exception):
    """Only static, credential-free messages may be included."""


def require(condition, message):
    if not condition:
        raise MigrationError(message)


def schema_signature(connection):
    result = {}
    result["columns"] = connection.execute(
        """
        SELECT c.relname, a.attnum, a.attname, format_type(a.atttypid,a.atttypmod),
               a.attnotnull, pg_get_expr(d.adbin,d.adrelid)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname='public' AND c.relname=ANY(%s)
          AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname,a.attnum
        """,
        (list(TABLES),),
    ).fetchall()
    result["constraints"] = connection.execute(
        """
        SELECT c.relname,k.conname,pg_get_constraintdef(k.oid)
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s)
        ORDER BY c.relname,k.conname
        """,
        (list(TABLES),),
    ).fetchall()
    result["indexes"] = connection.execute(
        "SELECT tablename,indexname,indexdef FROM pg_indexes "
        "WHERE schemaname='public' AND tablename=ANY(%s) ORDER BY tablename,indexname",
        (list(TABLES),),
    ).fetchall()
    return result


def extensions(connection):
    return dict(connection.execute("SELECT extname,extversion FROM pg_extension").fetchall())


def relations(connection):
    return connection.execute(
        """
        SELECT n.nspname,c.relname,c.relkind FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
        ORDER BY 1,2
        """
    ).fetchall()


def restore_list(catalog):
    # Vector stays an administrator task; preserve existing ownership and comments.
    lines = catalog.splitlines()
    removed = [
        line
        for line in lines
        if re.search(r"\b(?:EXTENSION - vector|COMMENT - EXTENSION vector)\s*$", line)
    ]
    require(len(removed) == 2, "Unexpected vector entries in archive; review the catalog")
    return "\n".join(line for line in lines if line not in removed) + "\n"


def write_private(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backup", required=True, type=Path, help="Directory containing manifest.json"
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--defer-unused-vector",
        action="store_true",
        help="Allow an administrator to enable optional unused pgvector after core transfer",
    )
    args = parser.parse_args()
    attempt = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    committed = False
    try:
        settings = Settings()
        require(
            settings.db_host == "192.168.1.51"
            and settings.db_name == "jobmitra_dev"
            and settings.db_port == 5432,
            "Expected target 192.168.1.51:5432/jobmitra_dev in environment settings",
        )
        manifest = json.loads((args.backup / "manifest.json").read_text())
        require(manifest["status"] == "backup_verified", "Backup is not marked verified")
        require(
            manifest["source"] == {"host": "127.0.0.1", "port": 5432, "database": "jobmitra_dev"},
            "Unexpected backup source",
        )
        require(set(manifest["table_fingerprints"]) == set(TABLES), "Unexpected backup tables")
        require(manifest["archive"] == "jobmitra_dev.dump", "Unexpected archive filename")
        archive = (args.backup / manifest["archive"]).resolve()
        require(
            hashlib.sha256(archive.read_bytes()).hexdigest() == manifest["archive_sha256"],
            "Archive checksum mismatch",
        )
        pg_restore = shutil.which("pg_restore")
        require(pg_restore is not None, "PostgreSQL 18 pg_restore is required")
        tool_version = subprocess.run(
            [pg_restore, "--version"], capture_output=True, text=True, check=True
        ).stdout
        require("(PostgreSQL) 18." in tool_version, "PostgreSQL 18 pg_restore is required")
        with psycopg.connect(
            **connection_kwargs(settings, "127.0.0.1", user="jobmitra_app")
        ) as source:
            source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            require(
                fingerprint(source) == manifest["table_fingerprints"],
                "Source changed since backup; create a fresh backup before migrating",
            )
            expected_schema = schema_signature(source)
            expected_extensions = {e["name"]: e["version"] for e in manifest["extensions"]}
            require(
                extensions(source) == expected_extensions, "Source extensions changed since backup"
            )
            non_builtin_columns = source.execute(
                """
                SELECT count(*) FROM pg_attribute a
                JOIN pg_class c ON c.oid=a.attrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_type t ON t.oid=a.atttypid
                JOIN pg_namespace tn ON tn.oid=t.typnamespace
                WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
                  AND c.relkind IN ('r','p','v','m','f') AND a.attnum>0
                  AND NOT a.attisdropped AND tn.nspname<>'pg_catalog'
                """
            ).fetchone()[0]
            require(
                not args.defer_unused_vector or non_builtin_columns == 0,
                "Cannot defer extensions when source columns use non-builtin types",
            )

        def compatible_extensions(actual):
            allowed = [expected_extensions]
            if args.defer_unused_vector:
                allowed.append(
                    {key: value for key, value in expected_extensions.items() if key != "vector"}
                )
            return actual in allowed

        with psycopg.connect(**connection_kwargs(settings, settings.db_host)) as target:
            target.execute("SET TRANSACTION READ ONLY")
            require(target.info.server_version // 10000 == 18, "PostgreSQL 18 target required")
            require(
                target.execute("SELECT current_schema()").fetchone()[0] == "public",
                "Unexpected target default schema",
            )
            target_extensions = extensions(target)
            require(
                compatible_extensions(target_extensions),
                "Target extensions must match source: "
                "enable vector 0.8.7 as PostgreSQL administrator",
            )
            target_relations = relations(target)
            if target_relations:
                target_tables = {
                    (schema, name) for schema, name, kind in target_relations if kind in {"r", "p"}
                }
                require(
                    target_tables == {("public", name) for name in TABLES}
                    and schema_signature(target) == expected_schema
                    and fingerprint(target) == manifest["table_fingerprints"],
                    "Target contains existing objects or different records; "
                    "nothing was overwritten",
                )
                print(json.dumps({"status": "already_migrated", "records_unchanged": True}))
                return 0
            require(
                target.execute(
                    "SELECT has_schema_privilege(current_user,'public','CREATE')"
                ).fetchone()[0],
                "Target application user needs CREATE on public schema",
            )

        catalog = subprocess.run(
            [pg_restore, "--list", str(archive)], capture_output=True, text=True, check=True
        ).stdout
        selected = restore_list(catalog)
        list_path = args.backup / f"{attempt}-restore.list"
        write_private(list_path, selected)
        schema_path = args.backup / f"{attempt}-restore-schema.sql"
        descriptor = os.open(schema_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            decoded = subprocess.run(
                [
                    pg_restore,
                    "--schema-only",
                    "--no-owner",
                    "--no-acl",
                    "--use-list",
                    str(list_path),
                    "--file=-",
                    str(archive),
                ],
                stdout=stream,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        require(decoded.returncode == 0, "Could not decode restore schema")
        report = {
            "status": "preflight_passed",
            "target": {
                "host": settings.db_host,
                "port": settings.db_port,
                "database": settings.db_name,
            },
            "target_was_empty": True,
            "archive_sha256": manifest["archive_sha256"],
            "table_fingerprints": manifest["table_fingerprints"],
            "extensions": expected_extensions,
            "target_extensions": target_extensions,
            "deferred_extensions": sorted(expected_extensions.keys() - target_extensions.keys()),
            "schema_file": str(schema_path),
            "single_transaction": True,
            "source_unchanged": True,
            "restore_attempted": False,
        }
        if args.apply:
            process = subprocess.run(
                [
                    pg_restore,
                    "--single-transaction",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                    "--no-password",
                    "--use-list",
                    str(list_path),
                    "--host",
                    settings.db_host,
                    "--port",
                    str(settings.db_port),
                    "--username",
                    settings.db_user,
                    "--dbname",
                    settings.db_name,
                    str(archive),
                ],
                capture_output=True,
                env=pg_environment(settings),
                timeout=120,
            )
            require(
                process.returncode == 0,
                "Restore did not report success; "
                "inspect target before retrying; details suppressed",
            )
            committed = True
            with psycopg.connect(**connection_kwargs(settings, settings.db_host)) as target:
                target.execute("SET TRANSACTION READ ONLY")
                require(
                    fingerprint(target) == manifest["table_fingerprints"],
                    "Restore finished but row hashes differ; review before using the target",
                )
                require(schema_signature(target) == expected_schema, "Restored schema differs")
                final_extensions = extensions(target)
                require(compatible_extensions(final_extensions), "Target extension versions differ")
                report["target_extensions"] = final_extensions
                report["deferred_extensions"] = sorted(
                    expected_extensions.keys() - final_extensions.keys()
                )
            with psycopg.connect(
                **connection_kwargs(settings, "127.0.0.1", user="jobmitra_app")
            ) as source:
                source.execute("SET TRANSACTION READ ONLY")
                require(
                    fingerprint(source) == manifest["table_fingerprints"],
                    "Source changed during migration",
                )
            report.update(
                status="migration_verified",
                restore_attempted=True,
                all_row_hashes_match=True,
                schema_matches=True,
                source_unchanged=True,
            )
        report_path = args.backup / f"{attempt}-{'apply' if args.apply else 'check'}.json"
        write_private(report_path, json.dumps(report, indent=2) + "\n")
        print(json.dumps({**report, "report": str(report_path)}))
        return 0
    except Exception as error:
        result = {"status": "not_verified", "restore_reported_success": committed}
        if isinstance(error, MigrationError):
            result["message"] = str(error)
        else:
            result.update(database_failure_details(error))
        print(json.dumps(result))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

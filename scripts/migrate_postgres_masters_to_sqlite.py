"""Safely copy legacy PostgreSQL masters to the experimental SQLite ATS store.

Dry run is the default. PostgreSQL is always read-only. Execute backs up SQLite,
upgrades it explicitly, appends records, verifies every source ID and commits once.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from jobmitra.core.config import Settings  # noqa: E402
from jobmitra.core.database import build_engine  # noqa: E402
from jobmitra.modules.ats_v2.database import build_ats_engine, validate  # noqa: E402
from jobmitra.modules.ats_v2.master_import import (  # noqa: E402
    ImportConflict,
    execute_import,
    integrity,
    local_state,
    plan_import,
    plan_report,
    state_counts,
)
from jobmitra.modules.ats_v2.master_source import (  # noqa: E402
    SourceError,
    load_snapshot,
    read_source,
    write_private_json,
)
from jobmitra.modules.ats_v2.resumes import safe_resume_path  # noqa: E402


def private_artifact(path):
    path = Path(path).expanduser().resolve()
    if path.is_relative_to(PROJECT):
        result = subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=PROJECT)
        if result.returncode != 0:
            raise SourceError(
                "Migration reports must be outside Git tracking or in ignored runtime storage."
            )
    return path


def summary(report, report_path):
    print("Mode:", report["mode"], "| Status:", report["status"])
    print("PostgreSQL source companies:", report.get("source_counts", {}).get("companies", 0))
    print("PostgreSQL source candidates:", report.get("source_counts", {}).get("candidates", 0))
    print("SQLite counts before:", json.dumps(report.get("before_counts", {}), sort_keys=True))
    print("Records ready:", json.dumps(report.get("ready", {}), sort_keys=True))
    print("Already imported:", json.dumps(report.get("already_imported", {}), sort_keys=True))
    print("Conflicts:", json.dumps(report.get("conflict_codes", {}), sort_keys=True))
    print("Warnings:", json.dumps(report.get("warning_codes", {}), sort_keys=True))
    print("Resume file plan:", json.dumps(report.get("resume_file_plan", {}), sort_keys=True))
    if "imported" in report:
        print("Imported:", json.dumps(report["imported"], sort_keys=True))
        print("SQLite counts after:", json.dumps(report["after_counts"], sort_keys=True))
        print("Resume files copied:", report["copied_files"])
        print("SQLite backup:", report.get("backup") or "No changes; no new backup required")
    if report.get("error"):
        print("Error:", report["error"])
    print("Private verification report:", report_path)
    print("No PostgreSQL source rows were modified.")


def verify_files(state, storage_root):
    count = 0
    for row in state.get("candidate_resumes", []):
        if not row.get("legacy_postgres_id") or not row.get("storage_path"):
            continue
        path = safe_resume_path(storage_root, row["storage_path"])
        meta = json.loads(row["parsed_json"] or "{}")
        if not path.is_file():
            raise ImportConflict("A copied resume file is missing; verification failed.")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != meta.get("sha256") or path.stat().st_size != meta.get("size"):
            raise ImportConflict("A copied resume file failed integrity verification.")
        count += 1
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--verify", action="store_true")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--companies-only", action="store_true")
    scope.add_argument("--candidates-only", action="store_true")
    parser.add_argument(
        "--source-snapshot",
        type=Path,
        help="Use a previously captured private snapshot for dry run/verification only.",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--backup-directory", type=Path, default=PROJECT / "backups/ats-master-migration"
    )
    args = parser.parse_args(argv)
    if args.execute and args.source_snapshot:
        parser.error(
            "Execute must read current PostgreSQL source; snapshots are for planning/verification."
        )
    mode_name = "execute" if args.execute else "verify" if args.verify else "dry-run"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report = {"mode": mode_name, "status": "failed", "executed_at": stamp}
    postgres, sqlite = None, None
    report_path = private_artifact(
        args.report or PROJECT / "runtime/ats-master-migration" / f"{mode_name}-{stamp}.json"
    )
    try:
        settings = Settings()
        if not settings.ats_v2_database or not settings.ats_v2_database.is_file():
            raise SourceError(
                "Configured ATS database is absent; no database will be created automatically."
            )
        sqlite = build_ats_engine(settings.ats_v2_database)
        validate(sqlite, allow_v1=not args.verify)
        if args.source_snapshot:
            source = load_snapshot(args.source_snapshot)
            snapshot_path = args.source_snapshot.resolve()
            report["source_mode"] = "captured_snapshot"
        else:
            postgres = build_engine(settings)
            source = read_source(postgres)
            snapshot_path = write_private_json(
                private_artifact(PROJECT / "runtime/ats-master-migration" / f"source-{stamp}.json"),
                source,
            )
            report["source_mode"] = "live_read_only_postgresql"
        report.update(
            source_snapshot=str(snapshot_path),
            source_fingerprint=source["source_fingerprint"],
            discovered_source_schema=source["schema"],
            catalog=source["catalog"],
            missing_optional_tables=source["missing_optional_tables"],
        )
        companies, candidates = not args.candidates_only, not args.companies_only
        with sqlite.connect() as conn:
            before = local_state(conn)
        plan = plan_import(
            source,
            before,
            companies=companies,
            candidates=candidates,
            source_root=settings.document_storage_root,
        )
        report.update(plan_report(plan))
        if plan["conflicts"]:
            raise ImportConflict(
                "Unresolved conflicts require review; no records were overwritten."
            )
        if args.execute:
            result = execute_import(
                sqlite,
                source,
                backup_directory=args.backup_directory,
                storage_root=settings.ats_v2_resume_storage_root,
                source_root=settings.document_storage_root,
                companies=companies,
                candidates=candidates,
                source_verifier=lambda: read_source(postgres),
            )
            report.update(result)
            with sqlite.connect() as conn:
                report["copied_files_verified"] = verify_files(
                    local_state(conn), settings.ats_v2_resume_storage_root
                )
        elif args.verify:
            if any(plan[key] for key in ("companies", "candidates", "resumes")):
                raise ImportConflict(
                    "Source records remain unimported; verification is incomplete."
                )
            with sqlite.connect() as conn:
                integrity(conn)
                state = local_state(conn)
                report["copied_files_verified"] = verify_files(
                    state, settings.ats_v2_resume_storage_root
                )
                report["after_counts"] = state_counts(state)
            report.update(
                status="verified",
                integrity_check="ok",
                foreign_key_check="ok",
                source_id_reconciliation="ok",
            )
        else:
            report["status"] = "validated_dry_run"
        write_private_json(report_path, report)
        summary(report, report_path)
        return 0
    except Exception as error:
        if isinstance(error, (ImportConflict, SourceError)):
            report["error"] = str(error)
        else:
            report["error"] = (
                "Migration failed safely ("
                + type(error).__name__
                + "). Review private diagnostics; no source data was changed."
            )
        report["status"] = "failed"
        if not report_path.exists():
            write_private_json(report_path, report)
        summary(report, report_path)
        return 1
    finally:
        if sqlite is not None:
            sqlite.dispose()
        if postgres is not None:
            postgres.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

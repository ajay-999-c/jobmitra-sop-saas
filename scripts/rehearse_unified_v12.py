"""Rehearse V2 -> V3 on new private copies only. No live-cutover option exists."""

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from sqlalchemy import text

from jobmitra.core.config import Settings
from jobmitra.modules.ats_v2.database import (
    build_ats_engine,
    transaction,
    upgrade_unified,
    validate,
)
from jobmitra.modules.ats_v2.master_import import local_state, preserve_existing


def backup(source, destination):
    if not source.is_file() or destination.exists():
        raise RuntimeError("Use an existing source and a new destination.")
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    configured = Settings().ats_v2_database
    if configured and output.is_relative_to(configured.resolve()):
        parser.error("The configured production file cannot be a rehearsal output.")
    os.umask(0o077)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    clone, rollback = output / "ats-v3.sqlite3", output / "rollback.sqlite3"
    backup(source, clone)
    backup(source, rollback)
    engine, interrupted = build_ats_engine(clone), build_ats_engine(rollback)
    try:
        validate(engine)
        with engine.connect() as conn:
            before = local_state(conn)
            original_objects = list(
                conn.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")
            )
        try:
            with transaction(interrupted) as conn:
                upgrade_unified(conn)
                raise RuntimeError("Rehearsal rollback")
        except RuntimeError as error:
            if str(error) != "Rehearsal rollback":
                raise
        with interrupted.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA user_version").scalar_one() == 2
            assert (
                list(
                    conn.exec_driver_sql(
                        "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
                    )
                )
                == original_objects
            )
            assert local_state(conn) == before
        upgrade_unified(engine)
        with engine.connect() as conn:
            preserve_existing(conn, before)
            after = local_state(conn)
            assert conn.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").first() is None
            assert conn.scalar(text("SELECT count(*) FROM company_audit_events")) == 0
            contacts = conn.scalar(
                text("SELECT sum(json_array_length(contacts_json)) FROM companies")
            )
        upgrade_unified(engine)
        with engine.connect() as conn:
            assert local_state(conn) == after
        validate(engine)
        report = {
            "status": "PASSED",
            "source": str(source),
            "development_clone": str(clone),
            "version": 3,
            "before_counts": {t: len(r) for t, r in before.items()},
            "after_counts": {t: len(r) for t, r in after.items()},
            "contacts": contacts,
            "existing_fields_and_ids_preserved": True,
            "repeated_upgrade_no_changes": True,
            "forced_rollback_passed": True,
            "production_migrated": False,
            "original_row_fingerprints": {
                t: hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()
                for t, r in before.items()
            },
        }
        with (output / "rehearsal-report.json").open("x") as handle:
            json.dump(report, handle, indent=2)
        print(json.dumps(report))
    finally:
        engine.dispose()
        interrupted.dispose()


if __name__ == "__main__":
    main()

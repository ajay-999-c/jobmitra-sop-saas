"""Explicit optional V3 extension. Never installed by application startup."""

import argparse
import sqlite3
from functools import lru_cache
from pathlib import Path

from .database import _check, _objects, _statements, build_ats_engine, transaction

SCHEMA = Path(__file__).with_name("proposal_schema.sql")


@lru_cache
def extension_objects():
    with sqlite3.connect(":memory:") as conn:
        conn.executescript(SCHEMA.read_text())
        return _objects(conn.execute("SELECT type,name,sql FROM sqlite_master"))


def installed(conn):
    return bool(
        conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_proposals'"
        ).first()
    )


def install(engine):
    with transaction(engine) as conn:
        _check(conn)
        if conn.exec_driver_sql("PRAGMA user_version").scalar_one() != 3:
            raise RuntimeError("Proposal extension requires an existing validated V3 store.")
        if installed(conn):
            return
        for statement in _statements(SCHEMA):
            conn.exec_driver_sql(statement)
        _check(conn)


def main():
    from jobmitra.core.local_v12 import LOCAL_ROOT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    path = args.database.absolute()
    if (
        path != LOCAL_ROOT / "ats-v3.sqlite3"
        or not path.is_file()
        or any(p.is_symlink() for p in [path, *path.parents])
        or path.stat().st_nlink != 1
    ):
        parser.error("CLI is restricted to the existing isolated runtime/v12-local V3 copy.")
    engine = build_ats_engine(path)
    try:
        install(engine)
        print("Optional proposal extension v1 installed on the isolated V3 copy only.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

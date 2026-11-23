"""Explicit installation of optional candidate profile evidence on isolated V3 only."""

import argparse
import sqlite3
from functools import lru_cache
from pathlib import Path

from .database import _check, _objects, _statements, build_ats_engine, transaction

SCHEMA = Path(__file__).with_name("profile_schema.sql")


@lru_cache
def extension_objects():
    with sqlite3.connect(":memory:") as conn:
        conn.executescript(SCHEMA.read_text())
        return _objects(conn.execute("SELECT type,name,sql FROM sqlite_master"))


def installed(conn):
    from .database import has_table

    return has_table(conn, "candidate_profile_versions")


def install(engine):
    with transaction(engine) as conn:
        _check(conn)
        if conn.exec_driver_sql("PRAGMA user_version").scalar_one() != 3:
            raise RuntimeError("Candidate profiles require an existing validated V3 copy.")
        if installed(conn):
            return
        for statement in _statements(SCHEMA):
            conn.exec_driver_sql(statement)
        _check(conn)


def main():
    from jobmitra.core.local_v12 import LOCAL_ROOT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    p = args.database.absolute()
    if (
        p != LOCAL_ROOT / "ats-v3.sqlite3"
        or not p.is_file()
        or p.stat().st_nlink != 1
        or any(q.is_symlink() for q in [p, *p.parents])
    ):
        parser.error("Only the existing isolated runtime/v12-local V3 copy is allowed.")
    engine = build_ats_engine(p)
    try:
        install(engine)
        print("Candidate profile extension installed only on isolated V3.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

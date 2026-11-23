"""Explicit, atomic EMAIL constraint extension on an isolated development V3 copy only."""

import argparse
import sqlite3
from functools import lru_cache
from pathlib import Path

from .common import AtsError
from .database import _check, _objects, _statements, build_ats_engine

SCHEMA = Path(__file__).with_name("registration_schema.sql")
OLD_SOURCES = "'MANUAL','WALK_IN','FOUNDIT_PASTE','RESUME_UPLOAD','OTHER'"


def email_table(sql):
    if OLD_SOURCES not in sql:
        raise RuntimeError("Unexpected candidate source constraint; no schema changed.")
    return sql.replace(OLD_SOURCES, OLD_SOURCES + ",'EMAIL'").replace(
        "CREATE TABLE candidates (", 'CREATE TABLE "candidates" (', 1
    )


@lru_cache
def extension_objects():
    with sqlite3.connect(":memory:") as conn:
        conn.executescript(SCHEMA.read_text())
        return _objects(conn.execute("SELECT type,name,sql FROM sqlite_master"))


def installed(conn):
    from .database import has_table

    if conn.dialect.name == "postgresql":
        return True  # EMAIL is part of the explicit PostgreSQL development schema.
    return has_table(conn, "candidate_registration_extension")


def ensure_source(conn, values):
    if values.get("source") == "EMAIL" and not installed(conn):
        raise AtsError(
            "Email source requires the explicit isolated V3 registration extension.", 409
        )


def _rows(conn):
    names = [
        r[0]
        for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        name: sorted(conn.exec_driver_sql('SELECT * FROM "' + name + '"').fetchall(), key=repr)
        for name in names
    }


def install(engine):
    # Never offered by application startup or an HTTP endpoint.
    from jobmitra.core.config import PROJECT_ENV_FILE

    path = Path(engine.url.database).absolute()
    runtime = PROJECT_ENV_FILE.parent / "runtime"
    if (
        not path.is_file()
        or not path.resolve().is_relative_to(runtime.resolve())
        or path.stat().st_nlink != 1
        or any(p.is_symlink() for p in [path, *path.parents])
    ):
        raise RuntimeError("Registration extension only accepts isolated runtime/ SQLite copies.")
    with engine.connect() as conn:
        _check(conn)
        if conn.exec_driver_sql("PRAGMA user_version").scalar_one() != 3:
            raise RuntimeError("Registration extension requires existing SQLite V3.")
        if installed(conn):
            return
        conn.rollback()
        # SQLite cannot ALTER a CHECK constraint. Rebuild only this table, with
        # all guards/views restored in the same exclusive transaction. No audit
        # trigger runs during copying, and every original row is reconciled.
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        conn.exec_driver_sql("BEGIN EXCLUSIVE")
        try:
            _check(conn)
            before = _rows(conn)
            objects = list(
                conn.exec_driver_sql(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL"
                )
            )
            sql = next(r[3] for r in objects if r[0] == "table" and r[1] == "candidates")
            for kind, name, _, _ in objects:
                if kind in {"trigger", "view"}:
                    conn.exec_driver_sql("DROP " + kind + ' "' + name + '"')
            new_sql = email_table(sql).replace(
                'CREATE TABLE "candidates" (', "CREATE TABLE candidates_email_new (", 1
            )
            conn.exec_driver_sql(new_sql)
            conn.exec_driver_sql("INSERT INTO candidates_email_new SELECT * FROM candidates")
            conn.exec_driver_sql("DROP TABLE candidates")
            conn.exec_driver_sql("ALTER TABLE candidates_email_new RENAME TO candidates")
            for kind, _, table, statement in objects:
                if kind in {"trigger", "view"} or (kind == "index" and table == "candidates"):
                    conn.exec_driver_sql(statement)
            for statement in _statements(SCHEMA):
                conn.exec_driver_sql(statement)
            conn.exec_driver_sql("INSERT INTO candidate_registration_extension(version) VALUES(1)")
            after = _rows(conn)
            if any(after[name] != rows for name, rows in before.items()):
                raise RuntimeError("Registration extension row reconciliation failed.")
            _check(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    engine = build_ats_engine(args.database)
    try:
        install(engine)
        print("Registration extension v1 verified on isolated V3 only.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

"""Explicit initialization and versioned upgrades for the isolated ATS store.

This module never imports the legacy PostgreSQL Base or runs Alembic. Schema
changes require a new reviewed SQLite version; unrelated or older databases are
refused rather than silently converted.
"""

import argparse
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

APPLICATION_ID = 1246576980
SCHEMA_VERSION = 2
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_V1_PATH = Path(__file__).with_name("schema_v1.sql")
UPGRADE_PATH = Path(__file__).with_name("upgrade_v1_to_v2.sql")
CORE_TABLES = frozenset(
    {
        "companies",
        "candidates",
        "candidate_resumes",
        "job_descriptions",
        "jd_interview_rounds",
        "jd_candidates",
        "recruitment_events",
        "candidate_activities",
    }
)


def build_ats_engine(path: Path) -> Engine:
    """Build a distinct SQLite engine. Call initialize explicitly before use."""
    path = Path(path).expanduser().resolve()
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(path)),
        connect_args={"check_same_thread": False, "timeout": 5},
        pool_pre_ping=True,
        echo=False,
        hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA recursive_triggers=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    return engine


def _statements(path: Path = SCHEMA_PATH) -> Iterator[str]:
    statement = ""
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            yield statement
            statement = ""
    if statement.strip():
        raise RuntimeError("The ATS schema contains an incomplete SQL statement.")


def _objects(rows) -> dict[tuple[str, str], str]:
    return {
        (row[0], row[1]): " ".join(row[2].split())
        for row in rows
        if row[2] is not None and not row[1].startswith("sqlite_")
    }


@lru_cache(maxsize=2)
def _expected_objects(version: int = SCHEMA_VERSION) -> dict[tuple[str, str], str]:
    path = SCHEMA_V1_PATH if version == 1 else SCHEMA_PATH
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(path.read_text(encoding="utf-8"))
        return _objects(connection.execute("SELECT type,name,sql FROM sqlite_master"))


def _check(connection: Connection, *, allow_v1: bool = False) -> bool:
    """Return False only for an entirely empty, unclaimed SQLite database."""
    objects = _objects(connection.exec_driver_sql("SELECT type,name,sql FROM sqlite_master"))
    application_id = connection.exec_driver_sql("PRAGMA application_id").scalar_one()
    version = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
    if not objects and application_id == 0 and version == 0:
        return False
    if application_id != APPLICATION_ID or version not in {1, SCHEMA_VERSION}:
        raise RuntimeError("Unsupported SQLite database. Use a new ATS V2 database path.")
    if objects != _expected_objects(version):
        raise RuntimeError("ATS V2 schema differs from its version. No migration was applied.")
    if connection.exec_driver_sql("PRAGMA quick_check").scalar_one() != "ok":
        raise RuntimeError("ATS V2 database integrity check failed.")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("ATS V2 database contains broken references.")
    if version == 1 and not allow_v1:
        raise RuntimeError(
            "ATS schema version 1 requires an explicit reviewed upgrade to version 2."
        )
    return True


def validate(engine: Engine, *, allow_v1: bool = False) -> None:
    """Validate the existing store without initializing or altering its schema."""
    with engine.connect() as connection:
        if not _check(connection, allow_v1=allow_v1):
            raise RuntimeError("ATS V2 database is not initialized. Run its explicit initializer.")


def upgrade(store: Engine | Connection) -> None:
    """Explicitly upgrade an exact V1 store, preserving its rows and audit events.

    Passing a Connection composes the schema change with the caller's migration
    transaction and never commits it. Passing an Engine owns a serialized write
    transaction. Runtime startup only calls validate and never calls this helper.
    Company references retained from V1 must be resolved by the reviewed import;
    callers must validate them after importing companies and before committing.
    """
    if isinstance(store, Engine):
        if store.dialect.name != "sqlite":
            raise ValueError("ATS upgrades only accept the isolated SQLite engine.")
        with transaction(store) as connection:
            upgrade(connection)
        return
    if store.dialect.name != "sqlite" or not store.in_transaction():
        raise ValueError("Pass an active SQLite transaction to compose the ATS upgrade.")
    # pysqlite's legacy transaction mode does not emit BEGIN for SELECT or DDL.
    # An SQLAlchemy transaction alone is insufficient to make ALTER rollback.
    if not store.connection.driver_connection.in_transaction:
        store.exec_driver_sql("BEGIN IMMEDIATE")
    if not _check(store, allow_v1=True):
        raise RuntimeError("Initialize a new ATS store before requesting an upgrade.")
    version = store.exec_driver_sql("PRAGMA user_version").scalar_one()
    if version == SCHEMA_VERSION:
        return
    for statement in _statements(UPGRADE_PATH):
        store.exec_driver_sql(statement)
    _check(store)


def initialize(engine: Engine) -> None:
    """Initialize a new/empty store, or verify an existing matching store.

    Schema creation and version markers commit together. An existing unrelated
    database is inspected before WAL or DDL changes are attempted.
    """
    if engine.dialect.name != "sqlite":
        raise ValueError("ATS V2 initialization only accepts its SQLite engine.")
    with engine.connect() as connection:
        ready = _check(connection)
        connection.rollback()
        if ready:
            return
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.rollback()
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            if not _check(connection):
                for statement in _statements():
                    connection.exec_driver_sql(statement)
                _check(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """Serialize short write transactions and roll back every failure."""
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def get_ats_session(request: Request) -> Iterator[Session]:
    """ATS session factory, intentionally separate from get_session/PostgreSQL."""
    with Session(request.app.state.ats_v2_engine) as session:
        yield session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    arguments = parser.parse_args()
    path = arguments.database.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = build_ats_engine(path)
    try:
        initialize(engine)
        print(f"ATS V2 schema {SCHEMA_VERSION} verified: {path}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

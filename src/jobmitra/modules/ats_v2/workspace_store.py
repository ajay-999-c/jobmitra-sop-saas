"""Explicit, additive JD workspace extension. Never invoked during application startup.

Production uses the existing public.staff_members UUID master. Disposable tests may
point the view/FK at a copy of that *same model* in their own namespace.
"""

import hashlib
import json
import sqlite3
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text

from .common import AtsError
from .database import has_table

OBJECTS = frozenset({"jd_workspace_versions", "v_employee_directory"})
SQL_PATH = Path(__file__).with_name("workspace_v1.sql")
SQLITE_PATH = Path(__file__).with_name("workspace_v1_sqlite.sql")


def digest():
    return hashlib.sha256(SQL_PATH.read_bytes()).hexdigest()


def installed(conn):
    if not hasattr(conn.engine, "_jd_workspace_installed"):
        conn.engine._jd_workspace_installed = has_table(conn, "jd_workspace_versions")
    return conn.engine._jd_workspace_installed


def require(conn):
    if not installed(conn):
        raise AtsError(
            "The reviewed JD workspace migration is required. No automatic migration was run.", 503
        )


def revision(job):
    fields = {
        k: v
        for k, v in dict(job).items()
        if k
        not in {
            "revision",
            "joined_count",
            "candidate_count",
            "target_state",
            "days_remaining",
            "assigned_recruiter_name",
            "assigned_recruiter_active",
        }
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


def assignment(conn, employee_id, old_id=None):
    if str(employee_id or "").replace("-", "") == str(old_id or "").replace("-", ""):
        return
    require(conn)
    if (
        employee_id
        and not conn.execute(
            text(
                "SELECT id FROM v_employee_directory WHERE "
                "replace(id,'-','')=replace(:id,'-','') AND is_active"
            ),
            {"id": str(employee_id)},
        ).first()
    ):
        raise AtsError("Select an existing active employee for a new assignment.")


def apply_postgres(conn, schema, staff_schema="public"):
    """Caller owns transaction and backups. Existing office namespace is not a default."""
    from .postgres import checked_schema

    checked_schema(schema)
    if staff_schema != "public":
        checked_schema(staff_schema)
    exists = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema=%s "
        "AND table_name='jd_workspace_versions'",
        (schema,),
    ).fetchone()
    if exists:
        marker = conn.execute(
            f'SELECT version,definition_sha256,staff_schema FROM "{schema}".jd_workspace_versions'
        ).fetchall()
        if marker != [(1, digest(), staff_schema)]:
            raise RuntimeError("Workspace extension manifest mismatch")
        return
    conn.execute(
        SQL_PATH.read_text()
        .replace("__V12_SCHEMA__", schema)
        .replace("__STAFF_SCHEMA__", staff_schema),
        prepare=False,
    )
    conn.execute(
        f'INSERT INTO "{schema}".jd_workspace_versions VALUES(1,%s,%s)', (digest(), staff_schema)
    )


def storage_id(conn, value):
    return str(value).replace("-", "") if value and conn.dialect.name == "sqlite" else value


def apply_sqlite(engine):
    """Explicit isolated-copy extension; startup never calls this."""
    from .database import _check, _statements, transaction

    with transaction(engine) as conn:
        _check(conn)
        if installed(conn):
            return
        for statement in _statements(SQLITE_PATH):
            conn.exec_driver_sql(statement)
        conn.execute(
            text("INSERT INTO jd_workspace_versions VALUES(1,:hash,'main')"),
            {"hash": hashlib.sha256(SQLITE_PATH.read_bytes()).hexdigest()},
        )
        _check(conn)
    engine._jd_workspace_installed = True


@lru_cache(maxsize=1)
def sqlite_objects():
    from .database import SCHEMA_PATH, UNIFIED_UPGRADE_PATH, _objects

    with sqlite3.connect(":memory:") as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.executescript(UNIFIED_UPGRADE_PATH.read_text())
        conn.executescript(SQLITE_PATH.read_text())
        objects = _objects(conn.execute("SELECT type,name,sql FROM sqlite_master"))
        return {
            k: v
            for k, v in objects.items()
            if k[1].startswith(("workspace_", "staff_", "jd_workspace_", "v_employee_"))
            or k == ("table", "job_descriptions")
        }

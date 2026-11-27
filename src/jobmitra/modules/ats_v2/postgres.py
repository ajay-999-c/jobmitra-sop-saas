"""Explicit, isolated PostgreSQL development store for the existing V12 services.

No provisioning, import, extension installation or backend fallback occurs here.
Only the reviewed development namespace is writable. Legacy and sealed snapshot
schemas are deliberately inaccessible through this engine's SQL boundary.
"""

import hashlib
import ipaddress
import os
import re
from pathlib import Path

from sqlalchemy import create_engine, event, text

TABLES = frozenset(
    {
        "candidates",
        "companies",
        "candidate_resumes",
        "job_descriptions",
        "jd_interview_rounds",
        "jd_candidates",
        "recruitment_events",
        "candidate_activities",
        "company_audit_events",
        "candidate_profile_versions",
        "company_proposals",
        "company_proposal_signed_documents",
        "company_proposal_status_events",
        "backend_versions",
        "development_source_records",
        "v_candidate_allocation_eligibility",
        "v_candidate_jd_history",
        "v_company_placement_register",
        "v_jd_dashboard",
        "v_jd_stage_counts",
    }
)
FUNCTIONS = frozenset({"json_extract", "json_each", "json_array_length", "julianday", "strftime"})
TOKEN = re.compile(
    r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*(?:\n|$)|/\*[\s\S]*?\*/"
    r"|%\([^)]+\)s|:[A-Za-z_]\w*|[A-Za-z_]\w*|\s+|.",
    re.DOTALL,
)
SQL_FILES = ("postgres_runtime.sql", "postgres_rules.sql")


def version_digest():
    return hashlib.sha256(
        b"\0".join(Path(__file__).with_name(p).read_bytes() for p in SQL_FILES)
    ).hexdigest()


def checked_schema(value):
    if not isinstance(value, str) or not re.fullmatch(r"jobmitra_v12_dev_[a-z0-9_]{1,35}", value):
        raise RuntimeError("PostgreSQL V12 requires an explicit jobmitra_v12_dev_* schema.")
    return value


def validate_configuration(settings):
    checked_schema(settings.v12_postgres_schema)
    if not (
        settings.v12_backend == "postgresql"
        and settings.v12_postgres_development
        and settings.unified_v12_enabled
        and settings.ats_v2_enabled
    ):
        raise RuntimeError(
            "PostgreSQL V12 requires explicit isolated-development opt-in and flags."
        )
    try:
        address = ipaddress.ip_address(settings.db_host)
    except ValueError:
        address = None
    local = (
        (address is not None and address.is_loopback)
        or settings.db_host == "localhost"
        or (os.name == "posix" and settings.db_host.startswith("/"))
    )
    if not (
        local
        or settings.db_sslmode == "verify-full"
        or (settings.v12_postgres_trusted_lan and address is not None and address.is_private)
    ):
        raise RuntimeError(
            "V12 PostgreSQL requires verified TLS or explicitly trusted private LAN."
        )


def scoped_sql(statement, schema):
    """Lex SQL identifiers, never literals/parameters, for the small existing query dialect.

    Repositories retain their tested bound parameters. Table/function references
    are explicit at execution; no search_path-based public fallback is possible.
    This is not a general SQLite SQL translator: PRAGMAs/DDL are refused.
    """
    checked_schema(schema)
    tokens = TOKEN.findall(statement)
    significant = [
        i for i, t in enumerate(tokens) if not t.isspace() and not t.startswith(("--", "/*"))
    ]
    words = [tokens[i].lower() for i in significant]
    if ";" in words[:-1]:
        raise RuntimeError("V12 runtime requires one parameterized statement.")
    if words and words[0] in {"pragma", "create", "alter", "drop", "truncate", "attach", "detach"}:
        raise RuntimeError("V12 runtime cannot run schema/SQLite operations.")
    for j, i in enumerate(significant):
        word, previous = words[j], words[j - 1] if j else ""
        following = words[j + 1] if j + 1 < len(words) else ""
        identifier = word.strip('"')
        if following == "." and identifier in {"public", "jobmitra_v12_stage"}:
            raise RuntimeError("V12 query attempted to access a protected schema.")
        table_position = previous in {"from", "join", "into", "update", "table"}
        if following == "." and table_position:
            if identifier not in {schema, "pg_catalog", "information_schema"}:
                raise RuntimeError("V12 query attempted to leave its isolated development schema.")
        if previous == "." or tokens[i].startswith(("'", "%(", ":")):
            continue
        from .workspace_store import OBJECTS

        if word.strip('"') in TABLES | OBJECTS and previous in {
            "from",
            "join",
            "into",
            "update",
            "table",
        }:
            tokens[i] = f'"{schema}"."{word.strip(chr(34))}"'
        elif word in FUNCTIONS and following == "(":
            tokens[i] = f'"{schema}"."{word}"'
        elif word == "like":
            tokens[i] = "ILIKE"  # SQLite LIKE is case-insensitive for the supported inputs.
        elif word == "collate" and following == "nocase":
            tokens[i] = tokens[significant[j + 1]] = ""
        elif word in {"desc", "asc"} and following != "nulls":
            tokens[i] += " NULLS LAST" if word == "desc" else " NULLS FIRST"
        elif word == "rowid":
            tokens[i] = "_record_order"
    return "".join(tokens)


def build_postgres_engine(settings):
    validate_configuration(settings)
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        echo=False,
        hide_parameters=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={
            "sslmode": settings.db_sslmode,
            "connect_timeout": settings.db_connect_timeout,
            "options": "-c search_path=pg_catalog -c timezone=UTC "
            "-c lock_timeout=10000 -c statement_timeout=30000",
        },
    )
    engine._v12_schema = checked_schema(settings.v12_postgres_schema)

    @event.listens_for(engine, "before_cursor_execute", retval=True)
    def scope_query(conn, cursor, statement, parameters, context, executemany):
        # SQLAlchemy dialect initialization uses only pg_catalog queries.
        def flags(values):
            if isinstance(values, dict):
                return {k: int(v) if type(v) is bool else v for k, v in values.items()}
            return tuple(int(v) if type(v) is bool else v for v in values)

        parameters = [flags(p) for p in parameters] if executemany else flags(parameters)
        return scoped_sql(statement, engine._v12_schema), parameters

    return engine


def begin_write(conn):
    # Match SQLite's proven short-writer semantics without locking any other
    # schema. Concurrent recruiters queue; receipts/stale checks run AFTER lock.
    # DB-level candidate row locks and a partial unique index additionally guard
    # selections made by another authorized SQL client.
    schema = checked_schema(conn.engine._v12_schema)
    conn.execute(
        text("SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext(:s),12012)"),
        {"s": schema},
    )


def validate_postgres(engine):
    schema = checked_schema(engine._v12_schema)
    with engine.connect() as conn:
        marker = conn.execute(
            text(f'SELECT version,definition_sha256,environment FROM "{schema}".backend_versions')
        ).all()
        if marker != [(1, version_digest(), "ISOLATED_DEVELOPMENT")]:
            raise RuntimeError("V12 PostgreSQL schema manifest mismatch; no migration performed.")
        names = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema=:s "
                    "AND table_type='BASE TABLE'"
                ),
                {"s": schema},
            ).scalars()
        )
        from . import workspace_store

        extended = "jd_workspace_versions" in names
        extension_tables = {"jd_workspace_versions"} if extended else set()
        if names - extension_tables != TABLES - {n for n in TABLES if n.startswith("v_")}:
            raise RuntimeError("V12 PostgreSQL table inventory mismatch.")
        if extended and conn.execute(
            text("SELECT version,definition_sha256 FROM jd_workspace_versions")
        ).all() != [(1, workspace_store.digest())]:
            raise RuntimeError("JD workspace extension manifest mismatch.")
        triggers = set(
            conn.execute(
                text(
                    "SELECT c.relname,t.tgname FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c "
                    "ON c.oid=t.tgrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=:s AND NOT t.tgisinternal AND t.tgenabled='O'"
                ),
                {"s": schema},
            ).all()
        )
        expected_triggers = {(t, "v12_guard_" + t) for t in names - extension_tables}
        expected_triggers |= {(t, "v12_no_truncate") for t in names - extension_tables}
        if extended:
            expected_triggers |= {
                ("job_descriptions", "workspace_recruiter_check"),
                ("job_descriptions", "workspace_recruiter_audit"),
            }
            expected_triggers.add(("jd_workspace_versions", "workspace_manifest_guard"))
        expected_triggers |= {
            (t, "v12_audit_" + t)
            for t in {
                "candidates",
                "companies",
                "job_descriptions",
                "jd_interview_rounds",
                "jd_candidates",
                "candidate_resumes",
                "candidate_activities",
            }
        }
        if triggers != expected_triggers:
            raise RuntimeError("V12 PostgreSQL business trigger inventory mismatch.")
        if conn.scalar(
            text(
                "SELECT count(*) FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.connamespace WHERE n.nspname=:s AND NOT c.convalidated"
            ),
            {"s": schema},
        ):
            raise RuntimeError("V12 PostgreSQL has unvalidated constraints.")
        if conn.scalar(
            text(
                "SELECT count(*) FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c "
                "ON c.oid=t.tgrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:s AND NOT t.tgisinternal AND t.tgenabled<>'O'"
            ),
            {"s": schema},
        ):
            raise RuntimeError("V12 PostgreSQL business protections are disabled.")

"""Read-only PostgreSQL inspection and private, reproducible master snapshots."""

import hashlib
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import MetaData, Table, inspect, select, text

from jobmitra.modules.candidates.models import (
    Candidate,
    CandidateDocument,
    CandidateResume,
    ResumeParseResult,
    WorkDomain,
    WorkSubdomain,
)
from jobmitra.modules.companies.models import Company, CompanyContact

SOURCE_MODELS = (
    Company,
    CompanyContact,
    Candidate,
    WorkDomain,
    WorkSubdomain,
    CandidateDocument,
    CandidateResume,
    ResumeParseResult,
)
SNAPSHOT_FORMAT = 1


class SourceError(Exception):
    """A safe message that never embeds driver parameters or candidate values."""


def json_value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat()
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    raise SourceError("A source value has an unsupported type; no import was performed.")


def canonical(value):
    return json.dumps(
        json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_source(engine):
    """Discover the actual catalog before SELECTing any mapped source table.

    A single REPEATABLE READ, READ ONLY transaction supplies the entire snapshot.
    No ORM metadata creation, migrations, writes, or employee queries occur.
    """
    if engine.dialect.name != "postgresql":
        raise SourceError("Master source must be the existing PostgreSQL engine.")
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    result = {
        "format": SNAPSHOT_FORMAT,
        "started_at": started,
        "tables": {},
        "catalog": {},
        "counts": {},
        "missing_optional_tables": [],
    }
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            if conn.scalar(text("SELECT 1")) != 1:
                raise SourceError("PostgreSQL SELECT 1 failed.")
            inspector = inspect(conn)
            schema = inspector.default_schema_name
            available = set(inspector.get_table_names(schema=schema))
            result["schema"] = schema
            result["discovered_table_names"] = sorted(available)
            for model in SOURCE_MODELS:
                name = model.__table__.name
                if name not in available:
                    if model in (Company, Candidate):
                        raise SourceError(
                            "A required master table is absent from the actual catalog."
                        )
                    result["missing_optional_tables"].append(name)
                    continue
                columns = inspector.get_columns(name, schema=schema)
                primary = inspector.get_pk_constraint(name, schema=schema)
                actual = {column["name"] for column in columns}
                required = (
                    {"id", "company_name"}
                    if model is Company
                    else ({"id", "full_name"} if model is Candidate else {"id"})
                )
                if not required <= actual:
                    raise SourceError("Actual source columns do not satisfy the master mapping.")
                result["catalog"][name] = {
                    "columns": [
                        {"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]}
                        for c in columns
                    ],
                    "primary_key": primary.get("constrained_columns", []),
                    "foreign_keys": inspector.get_foreign_keys(name, schema=schema),
                }
                table = Table(
                    name, MetaData(), schema=schema, autoload_with=conn, resolve_fks=False
                )
                query = select(table)
                if primary.get("constrained_columns"):
                    query = query.order_by(
                        *(table.c[key] for key in primary["constrained_columns"])
                    )
                rows = [json_value(dict(row)) for row in conn.execute(query).mappings()]
                result["tables"][name] = rows
                result["counts"][name] = len(rows)
            result["transaction_read_only"] = (
                conn.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
            )
    result["completed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    result["table_fingerprints"] = {
        name: fingerprint(rows) for name, rows in result["tables"].items()
    }
    result["source_fingerprint"] = fingerprint(result["table_fingerprints"])
    return result


def write_private_json(path, value):
    """Create, never overwrite, a private migration artifact."""
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            json_value(value), handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def load_snapshot(path):
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    if snapshot.get("format") != SNAPSHOT_FORMAT or not snapshot.get("transaction_read_only"):
        raise SourceError("Source snapshot format/read-only evidence is invalid.")
    actual = {name: fingerprint(rows) for name, rows in snapshot["tables"].items()}
    if actual != snapshot.get("table_fingerprints") or fingerprint(actual) != snapshot.get(
        "source_fingerprint"
    ):
        raise SourceError("Source snapshot integrity check failed.")
    if {name: len(rows) for name, rows in snapshot["tables"].items()} != snapshot.get("counts"):
        raise SourceError("Source snapshot counts do not reconcile.")
    return snapshot

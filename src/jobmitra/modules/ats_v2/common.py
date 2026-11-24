"""Errors and bounded helpers for the independent ATS SQLite workflow."""

import json
from datetime import UTC, datetime

from sqlalchemy import text

TABLES = frozenset(
    {
        "candidates",
        "candidate_resumes",
        "job_descriptions",
        "jd_interview_rounds",
        "jd_candidates",
        "recruitment_events",
        "candidate_activities",
    }
)


class AtsError(Exception):
    def __init__(self, message, status=422, code=None, *, matches=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.matches = matches


def one(connection, table, record_id):
    if table not in TABLES:
        raise ValueError("Unsupported ATS entity")
    row = (
        connection.execute(text(f"SELECT * FROM {table} WHERE id=:id"), {"id": record_id})
        .mappings()
        .first()
    )
    if row is None:
        raise AtsError("Record not found.", 404)
    return dict(row)


def utc_now():
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event_record(row):
    result = dict(row)
    for field in ("before_json", "after_json", "payload_json", "details_json"):
        if field in result and result[field] is not None:
            result[field] = json.loads(result[field])
    # Compatibility columns are not an attribution system.
    result.pop("actor_name", None)
    result.pop("assigned_to", None)
    return result

"""Basic registration reporting/browsing, separate from recruitment matching."""

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, get_args
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from .candidate_schemas import Source
from .candidates import candidate_dict
from .registration_store import installed

INDIA = ZoneInfo("Asia/Kolkata")
LABELS = {
    "MANUAL": "Manual",
    "WALK_IN": "Walk-in",
    "FOUNDIT_PASTE": "Foundit",
    "RESUME_UPLOAD": "Resume upload",
    "EMAIL": "Email",
    "OTHER": "Other",
}


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    period: Literal["ALL", "TODAY", "WEEK", "MONTH", "YEAR", "CUSTOM"] = "ALL"
    date_from: date | None = None
    date_to: date | None = None
    source: Source | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.period == "CUSTOM" and (
            self.date_from is None
            or self.date_to is None
            or self.date_from > self.date_to
            or self.date_to == date.max
        ):
            raise ValueError("Choose both dates in order; the end date is inclusive.")
        return self


class Directory(Filters):
    q: str = Field(default="", max_length=300)
    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=20, ge=1, le=100)


def bounds(filters, now=None):
    today = (now or datetime.now(UTC)).astimezone(INDIA).date()
    start = end = None
    if filters.period == "TODAY":
        start, end = today, today + timedelta(days=1)
    elif filters.period == "WEEK":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
    elif filters.period == "MONTH":
        start = today.replace(day=1)
        end = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    elif filters.period == "YEAR":
        start, end = date(today.year, 1, 1), date(today.year + 1, 1, 1)
    elif filters.period == "CUSTOM":
        start, end = filters.date_from, filters.date_to + timedelta(days=1)

    def utc(value):
        return datetime.combine(value, time.min, INDIA).astimezone(UTC).isoformat()

    return {
        "timezone": "Asia/Kolkata",
        "today": today.isoformat(),
        "start_date": start.isoformat() if start else None,
        "end_date": (end - timedelta(days=1)).isoformat() if end else None,
        "start_utc": utc(start) if start else None,
        "end_utc_exclusive": utc(end) if end else None,
    }


def clauses(filters, now=None):
    calendar = bounds(filters, now)
    conditions, params = ["1=1"], {}
    if calendar["start_utc"]:
        conditions.extend(
            [
                "julianday(c.created_at)>=julianday(:start)",
                "julianday(c.created_at)<julianday(:end)",
            ]
        )
        params.update(start=calendar["start_utc"], end=calendar["end_utc_exclusive"])
    if filters.source:
        conditions.append("c.source=:source")
        params["source"] = filters.source
    if isinstance(filters, Directory) and filters.q:
        literal = filters.q.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["q"] = "%" + literal + "%"
        parts = [
            f"lower(COALESCE(c.{field},'')) LIKE :q ESCAPE '\\'"
            for field in ["full_name", "phone", "email", "job_title"]
        ]
        digits = re.sub(r"\D", "", filters.q)
        if digits and re.fullmatch(r"[\d\s()+.\-]+", filters.q):
            params["digits"] = "%" + digits + "%"
            parts.append("c.phone_normalized LIKE :digits")
        conditions.append("(" + " OR ".join(parts) + ")")
    return " AND ".join(conditions), params, calendar


def source_options(conn):
    return [
        {"value": source, "label": LABELS[source]}
        for source in get_args(Source)
        if source != "EMAIL" or installed(conn)
    ]


def directory(engine, filters, now=None):
    where, params, calendar = clauses(filters, now)
    with engine.connect() as conn:
        # Count and page share a read snapshot, even during concurrent registration.
        conn.exec_driver_sql("BEGIN")
        total = conn.scalar(text("SELECT count(*) FROM candidates c WHERE " + where), params)
        rows = conn.execute(
            text(
                "SELECT c.* FROM candidates c WHERE "
                + where
                + " ORDER BY julianday(c.created_at) DESC,c.id DESC LIMIT :limit OFFSET :offset"
            ),
            {
                **params,
                "limit": filters.page_size,
                "offset": (filters.page - 1) * filters.page_size,
            },
        ).mappings()
        return {
            "items": [candidate_dict(row) for row in rows],
            "total": total,
            "page": filters.page,
            "page_size": filters.page_size,
            "pages": max(1, (total + filters.page_size - 1) // filters.page_size),
            "calendar": calendar,
            "sources": source_options(conn),
        }


def dashboard(engine, filters, now=None):
    where, params, calendar = clauses(filters, now)
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN")
        total = conn.scalar(text("SELECT count(*) FROM candidates"))
        count = conn.scalar(text("SELECT count(*) FROM candidates c WHERE " + where), params)
        recent = conn.execute(
            text(
                "SELECT c.* FROM candidates c WHERE "
                + where
                + " ORDER BY julianday(c.created_at) DESC,c.id DESC LIMIT 5"
            ),
            params,
        ).mappings()
        return {
            "total_candidates_all_time": total,
            "new_candidates_selected_period": count,
            "recent": [candidate_dict(row) for row in recent],
            "calendar": calendar,
            "sources": source_options(conn),
        }

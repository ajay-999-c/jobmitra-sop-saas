"""Bounded canonical JD browsing; the existing dashboard view owns target rules."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import text

from .candidate_registers import bounds
from .common import AtsError
from .database import begin_read
from .schemas import Input


class Filters(Input):
    q: str = Field(default="", max_length=300)
    company_id: UUID | None = None
    assigned_recruiter_id: UUID | None = None
    unassigned: bool = False
    status: Literal["DRAFT", "ACTIVE", "ON_HOLD", "CLOSED"] | None = None
    period: Literal["ALL", "TODAY", "WEEK", "MONTH", "YEAR", "CUSTOM"] = "ALL"
    date_from: date | None = None
    date_to: date | None = None
    target: Literal["TRACK", "DUE", "OVERDUE"] | None = None
    sort: Literal["NEWEST", "OLDEST", "TARGET", "COMPANY", "TITLE"] = "NEWEST"
    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def dates(self):
        if self.period == "CUSTOM" and (
            not self.date_from
            or not self.date_to
            or self.date_from > self.date_to
            or self.date_to == date.max
        ):
            raise ValueError("Choose both dates in order; the end date is inclusive.")
        return self


def browse(engine, filters, now=None):
    calendar = bounds(filters, now)
    postgres = engine.dialect.name == "postgresql"
    created = "CAST(d.created_at AS TIMESTAMPTZ)" if postgres else "julianday(d.created_at)"
    clauses, params = ["1=1"], {}
    from . import workspace_store

    with engine.connect() as connection:
        extended = workspace_store.installed(connection)
    if filters.q:
        literal = filters.q.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["q"] = "%" + literal + "%"
        clauses.append(
            "("
            + " OR ".join(
                f"lower(COALESCE({field},'')) LIKE :q ESCAPE '\\'"
                for field in [
                    "d.title",
                    "c.company_name",
                    "d.jd_code",
                    "CAST(d.id AS TEXT)",
                    "j.location",
                ]
                + (["e.display_name"] if extended else [])
            )
            + ")"
        )
    for field, value in [
        ("company_id", filters.company_id),
        ("status", filters.status),
        ("target_state", filters.target),
    ]:
        if value is not None:
            clauses.append(f"d.{field}=:{field}")
            params[field] = str(value)
    if filters.assigned_recruiter_id:
        if not extended:
            raise AtsError("Recruiter assignment migration is required", 503)
        clauses.append("j.assigned_recruiter_id=:recruiter")
        params["recruiter"] = (
            str(filters.assigned_recruiter_id).replace("-", "")
            if not postgres
            else str(filters.assigned_recruiter_id)
        )
    if filters.unassigned and extended:
        clauses.append("j.assigned_recruiter_id IS NULL")
    if calendar["start_utc"]:
        start = "CAST(:start AS TIMESTAMPTZ)" if postgres else "julianday(:start)"
        end = "CAST(:end AS TIMESTAMPTZ)" if postgres else "julianday(:end)"
        clauses.extend([f"{created}>={start}", f"{created}<{end}"])
        params.update(start=calendar["start_utc"], end=calendar["end_utc_exclusive"])
    join = (
        " FROM v_jd_dashboard d JOIN job_descriptions j ON j.id=d.id "
        "JOIN companies c ON c.id=d.company_id "
    )
    if extended:
        join += (
            "LEFT JOIN v_employee_directory e ON "
            "replace(e.id,'-','')=replace(CAST(j.assigned_recruiter_id AS TEXT),'-','') "
        )
    recruiter_fields = (
        ",j.assigned_recruiter_id,e.display_name AS assigned_recruiter_name,"
        "e.is_active AS assigned_recruiter_active"
        if extended
        else ",NULL AS assigned_recruiter_id,NULL AS assigned_recruiter_name"
    )
    where = " WHERE " + " AND ".join(clauses)
    ordering = {
        "NEWEST": f"{created} DESC,d.id DESC",
        "OLDEST": f"{created} ASC,d.id ASC",
        "TARGET": "CASE WHEN d.target_date IS NULL THEN 1 ELSE 0 END ASC,d.target_date ASC,"
        f"{created} DESC,d.id DESC",
        "COMPANY": f"lower(c.company_name) ASC,{created} DESC,d.id DESC",
        "TITLE": f"lower(d.title) ASC,{created} DESC,d.id DESC",
    }[filters.sort]
    with engine.connect() as conn:
        begin_read(conn)
        total = conn.scalar(text("SELECT count(*)" + join + where), params)
        rows = conn.execute(
            text(
                "SELECT d.*,j.location,c.company_name"
                + recruiter_fields
                + ",(SELECT count(*) FROM jd_candidates l "
                "WHERE l.job_id=d.id) candidate_count"
                + join
                + where
                + " ORDER BY "
                + ordering
                + " LIMIT :limit OFFSET :offset"
            ),
            {
                **params,
                "limit": filters.page_size,
                "offset": (filters.page - 1) * filters.page_size,
            },
        )
        items = [dict(r) for r in rows.mappings()]
        summary = dict(
            conn.execute(
                text(
                    "SELECT count(*) total,"
                    "COALESCE(sum(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END),0) active,"
                    "COALESCE(sum(CASE WHEN target_state='OVERDUE' THEN 1 ELSE 0 END),0) overdue,"
                    "COALESCE(sum(CASE WHEN target_state='DUE' THEN 1 ELSE 0 END),0) due_soon,"
                    "COALESCE(sum(CASE WHEN status='CLOSED' OR "
                    "(status='ACTIVE' AND target_state='FILLED') "
                    "THEN 1 ELSE 0 END),0) filled_closed FROM v_jd_dashboard"
                )
            )
            .mappings()
            .one()
        )
        companies = [
            dict(r)
            for r in conn.execute(
                text("SELECT id,company_name FROM companies ORDER BY lower(company_name),id")
            ).mappings()
        ]
        employees = (
            [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT id,display_name,is_active FROM v_employee_directory ORDER "
                        "BY lower(display_name),id"
                    )
                ).mappings()
            ]
            if extended
            else []
        )
    return {
        "items": items,
        "total": total,
        "summary": summary,
        "summary_scope": "ALL_JDS",
        "companies": companies,
        "employees": employees,
        "calendar": calendar,
        "page": filters.page,
        "page_size": filters.page_size,
        "pages": max(1, (total + filters.page_size - 1) // filters.page_size),
    }

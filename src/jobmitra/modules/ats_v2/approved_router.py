"""Canonical service adapters needed by the approved V12 controls."""

import json
from typing import Annotated
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import text

from jobmitra.core.workflow import same_origin

from . import (
    approved,
    candidate_registers,
    candidates,
    direct_movement,
    jd_dashboard,
    jobs,
    proposal,
    unified,
)
from . import request_receipts as receipts
from .attachment_corrections import CloseJD, Correction
from .candidate_schemas import SearchParams
from .common import AtsError, event_record, one
from .database import insert_result, transaction
from .jd_dashboard import Filters as JDDashboardFilters
from .parsed_router import router as parsed_router
from .profile_router import router as profile_router
from .proposal_router import router as proposal_pdf_router
from .router import AtsRoute
from .schemas import ActivityInput, FeedbackSource, LinkInput
from .unified_access import access
from .unified_router import Store

router = APIRouter(prefix="/approved", route_class=AtsRoute)
router.include_router(proposal_pdf_router)
router.include_router(profile_router)
router.include_router(parsed_router)


@router.post("/jobs/{job_id}/attach", status_code=201, dependencies=[Depends(same_origin)])
def attach_candidate(job_id: int, data: LinkInput, request: Request, engine: Store):
    access(request)
    return jobs.attach_contact(engine, job_id, data.candidate_id)


@router.post("/jobs/{job_id}/close", dependencies=[Depends(same_origin)])
def close_requirement(job_id: int, data: CloseJD, request: Request, engine: Store):
    from .attachment_corrections import close_job

    if request.headers.get("Idempotency-Key") != str(data.idempotency_key):
        raise AtsError("The closure reference and Idempotency-Key must match.")
    return close_job(engine, job_id, data, access(request))


@router.get("/jobs/{job_id}/candidates/{link_id}/attachment-correction")
def attachment_facts(job_id: int, link_id: int, engine: Store):
    from .attachment_corrections import facts

    with engine.connect() as conn:
        return facts(conn, job_id, link_id)


@router.post(
    "/jobs/{job_id}/candidates/{link_id}/attachment-correction", dependencies=[Depends(same_origin)]
)
def attachment_correct(
    job_id: int, link_id: int, data: Correction, request: Request, engine: Store
):
    from .attachment_corrections import correct

    if request.headers.get("Idempotency-Key") != str(data.idempotency_key):
        raise AtsError("The correction reference and Idempotency-Key must match.")
    return correct(engine, job_id, link_id, data, access(request))


@router.get("/jobs/{job_id}/candidates/{link_id}/destinations")
def direct_destinations(job_id: int, link_id: int, engine: Store):
    return direct_movement.choices(engine, job_id, link_id)


@router.post("/jobs/{job_id}/candidates/{link_id}/advance-to", dependencies=[Depends(same_origin)])
def direct_stage_move(
    job_id: int, link_id: int, data: direct_movement.DirectMove, request: Request, engine: Store
):
    role = access(request)
    if request.headers.get("Idempotency-Key") != str(data.idempotency_key):
        raise AtsError("The action reference and Idempotency-Key must match.")
    return direct_movement.move(engine, job_id, link_id, data, role)


@router.get("/jd-dashboard")
def jd_directory(engine: Store, filters: Annotated[JDDashboardFilters, Query()]):
    return jd_dashboard.browse(engine, filters)


@router.get("/jobs/{job_id}/state")
def selected_jd_state(job_id: int, request: Request, response: Response, engine: Store):
    import hashlib

    result = approved.state(engine, job_id)
    result["poll_seconds"] = request.app.state.settings.jd_poll_seconds
    tag = (
        '"'
        + hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
        + '"'
    )
    if request.headers.get("If-None-Match") == tag:
        return Response(
            status_code=304, headers={"ETag": tag, "Cache-Control": "private, no-cache"}
        )
    response.headers["ETag"] = tag
    response.headers["Cache-Control"] = "private, no-cache"
    return result


@router.get("/state")
def current_state(engine: Store):
    return approved.state(engine)


@router.get("/workspace-options")
def workspace_options(engine: Store):
    from . import workspace_store

    with engine.connect() as conn:
        companies = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT id,company_name,is_active,contacts_json FROM companies "
                    "ORDER BY company_name_key,id"
                )
            ).mappings()
        ]
        jobs_list = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT j.id,j.jd_code,j.title,j.status,c.company_name FROM job_descriptions j "
                    "JOIN companies c ON c.id=j.company_id ORDER BY j.created_at DESC,j.id DESC"
                )
            ).mappings()
        ]
        employees = (
            [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT id,display_name,is_active FROM v_employee_directory "
                        "ORDER BY lower(display_name),id"
                    )
                ).mappings()
            ]
            if workspace_store.installed(conn)
            else []
        )
    return {"companies": companies, "jobs": jobs_list, "employees": employees}


@router.get("/employee-options")
def employee_options(engine: Store):
    from . import workspace_store

    with engine.connect() as conn:
        workspace_store.require(conn)
        return [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT id,display_name,is_active FROM v_employee_directory ORDER "
                    "BY lower(display_name),id"
                )
            ).mappings()
        ]


@router.get("/search")
def search(engine: Store, params: Annotated[SearchParams, Query()]):
    return candidates.search_candidates(engine, params, include_names=True)


@router.get("/candidate-directory")
def directory(engine: Store, params: Annotated[candidate_registers.Directory, Query()]):
    return candidate_registers.directory(engine, params)


@router.get("/candidate-dashboard")
def dashboard(engine: Store, params: Annotated[candidate_registers.Filters, Query()]):
    return candidate_registers.dashboard(engine, params)


@router.post("/registration", status_code=201, dependencies=[Depends(same_origin)])
def register(data: approved.Registration, request: Request, engine: Store):
    access(request)
    return approved.register(engine, data, request.app.state.settings.ats_v2_resume_storage_root)


@router.patch("/companies/{company_id}", dependencies=[Depends(same_origin)])
def edit_company(company_id: UUID, data: approved.CompanyEdit, request: Request, engine: Store):
    return approved.edit_company(engine, str(company_id), data, access(request))


@router.post("/candidates/{candidate_id}/parsed", dependencies=[Depends(same_origin)])
def approve_parse(
    candidate_id: int, data: approved.ParsedApproval, request: Request, engine: Store
):
    return approved.approve_parse(engine, candidate_id, data, access(request))


class Outcome(unified.Action):
    feedback: str | None = Field(default=None, max_length=1500)
    feedback_source: FeedbackSource = "NOT_SPECIFIED"


@router.post("/jobs/{job_id}/candidates/{link_id}/outcome", dependencies=[Depends(same_origin)])
def record_outcome(job_id: int, link_id: int, data: Outcome, request: Request, engine: Store):
    role = access(request, supervisor=data.action == "REACTIVATE")
    facts = data.model_dump(mode="json")
    with transaction(engine) as conn:
        prior = receipts.replay(conn, "approved-outcome", [job_id, link_id, facts])
        if prior is not None:
            return jobs.linked(conn, job_id, link_id)
        action = unified.Action.model_validate(
            data.model_dump(exclude={"feedback", "feedback_source"})
        )
        action.idempotency_key = uuid5(data.idempotency_key, "canonical-outcome")
        result = unified.outcome(conn, job_id, link_id, action, role)
        if data.feedback:
            jobs.add_feedback(
                conn,
                one(conn, "job_descriptions", job_id),
                result,
                data.feedback,
                data.feedback_source,
            )
        receipts.record(
            conn,
            "approved-outcome",
            [job_id, link_id, facts],
            link_id,
            candidate_id=result["candidate_id"],
            job_id=job_id,
        )
        return result


class Activity(ActivityInput):
    details: dict = Field(default_factory=dict)


@router.post("/candidates/{candidate_id}/activity", dependencies=[Depends(same_origin)])
def record_activity(candidate_id: int, data: Activity, request: Request, engine: Store):
    access(request)
    if len(json.dumps(data.details).encode()) > 32000:
        raise AtsError("Activity details exceed the limit.")
    with transaction(engine) as conn:
        one(conn, "candidates", candidate_id)
        prior = receipts.replay(
            conn, "approved-activity", [candidate_id, data.model_dump(mode="json")]
        )
        if prior is not None:
            return event_record(one(conn, "candidate_activities", prior))
        if data.job_id:
            row = conn.execute(
                text("SELECT id FROM jd_candidates WHERE candidate_id=:c AND job_id=:j"),
                {"c": candidate_id, "j": data.job_id},
            ).first()
            if row is None:
                raise AtsError("Candidate must belong to the specified JD.", 409)
            jobs.linked(conn, data.job_id, row[0])
        values = data.model_dump(mode="json", exclude={"details"})
        values.update(candidate_id=candidate_id, details_json=json.dumps(data.details))
        aid = insert_result(
            conn,
            text(
                "INSERT INTO candidate_activities("
                + ",".join(values)
                + ") VALUES("
                + ",".join(":" + k for k in values)
                + ")"
            ),
            values,
        ).lastrowid
        receipts.record(
            conn,
            "approved-activity",
            [candidate_id, data.model_dump(mode="json")],
            aid,
            candidate_id=candidate_id,
        )
        return event_record(one(conn, "candidate_activities", aid))


@router.get("/candidates/{candidate_id}/parsed/{resume_id}")
def parsed_document(candidate_id: int, resume_id: int, request: Request, engine: Store):
    access(request)
    with engine.connect() as conn:
        row = one(conn, "candidate_resumes", resume_id)
        if row["candidate_id"] != candidate_id or row["resume_kind"] != "PARSED_TEXT":
            raise AtsError("Parsed version not found.", 404)
        payload = json.loads(row["parsed_json"] or "{}")
        return {"original_json_text": payload.get("original_source_json_text"), "payload": payload}


@router.get("/companies/{company_id}/proposal-context")
def proposal_context(company_id: UUID, engine: Store, company_contact_id: UUID | None = None):
    return proposal.context(
        engine, str(company_id), str(company_contact_id) if company_contact_id else None
    )


@router.get("/companies/{company_id}/proposal-studio", include_in_schema=False)
def proposal_studio(company_id: UUID, engine: Store, company_contact_id: UUID | None = None):
    proposal.context(
        engine, str(company_id), str(company_contact_id) if company_contact_id else None
    )
    return FileResponse(proposal.STUDIO_FILE, media_type="text/html")

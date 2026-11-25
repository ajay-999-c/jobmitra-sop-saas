"""Opt-in V12 pages and APIs. Requires explicitly migrated SQLite V3."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, SecretStr
from sqlalchemy.engine import Engine

from jobmitra.core.workflow import same_origin

from . import unified
from .common import AtsError, one
from .router import AtsRoute, ats_engine
from .schemas import Stage
from .unified_access import COOKIE, access, issue


def enabled(request: Request):
    if not request.app.state.settings.unified_v12_enabled:
        raise AtsError("Unified Workspace V12 is not enabled.", 404)


def unified_engine(engine: Annotated[Engine, Depends(ats_engine)]):
    with engine.connect() as conn:
        if not unified.is_v3(conn):
            raise AtsError(
                "V12 needs an explicitly reviewed SQLite V3 cutover. The existing "
                "database was not changed.",
                503,
            )
    return engine


Store = Annotated[Engine, Depends(unified_engine)]
router = APIRouter(route_class=AtsRoute, dependencies=[Depends(enabled)])
api = APIRouter(prefix="/api/v12", route_class=AtsRoute, dependencies=[Depends(enabled)])


@router.get("/workspace-v12", include_in_schema=False)
@router.get("/workspace-v12/{section}", include_in_schema=False)
def workspace(
    request: Request,
    engine: Store,
    section: Literal["companies", "candidates", "jobs"] = "companies",
):
    from jobmitra.core.pages import templates

    name = "v12/approved.html"
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={
            "base_template": "v12/base.html",
            "unified_v12": True,
            "workspace_section": section,
        },
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; connect-src"
            " 'self'; img-src 'self' data: blob:; frame-src 'self' blob:; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'",
        },
    )


class AccessInput(BaseModel):
    token: SecretStr


@api.post("/access", dependencies=[Depends(same_origin)])
def unlock(data: AccessInput, request: Request, response: Response):
    value = issue(request.app.state.settings, data.token.get_secret_value())
    response.set_cookie(
        COOKIE,
        value,
        max_age=8 * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return {"editing": True, "actor_identity": "Declared actor name; shared operator capability"}


@api.get("/access")
def current_access(request: Request):
    try:
        role = access(request)
        result = {"editing": True, "role": role}
        if role == "OFFICE_LAN":
            from jobmitra.core.office_lan import OFFICE_ACTOR

            result.update(office_lan=True, authentication_required=False, actor_name=OFFICE_ACTOR)
        if role == "LOCAL_DEVELOPMENT":
            from jobmitra.core.local_v12 import LOCAL_ACTOR

            result.update(local_development=True, actor_name=LOCAL_ACTOR)
        return result
    except AtsError:
        return {"editing": False, "role": None}


@api.delete("/access", dependencies=[Depends(same_origin)])
def lock(response: Response):
    response.delete_cookie(COOKIE)
    return {"editing": False}


@api.get("/companies")
def companies(
    engine: Store,
    q: str = Query("", max_length=300),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    return unified.directory(engine, q, page, page_size)


@api.get("/companies/{company_id}")
def company(company_id: UUID, engine: Store):
    return unified.company_records(engine, str(company_id))


@api.post("/companies", status_code=201, dependencies=[Depends(same_origin)])
def company_create(data: unified.CompanyCreate, request: Request, engine: Store):
    return unified.create_company(engine, data, access(request))


@api.patch("/companies/{company_id}", dependencies=[Depends(same_origin)])
def company_edit(company_id: UUID, data: unified.CompanyEdit, request: Request, engine: Store):
    return unified.edit_company(engine, str(company_id), data, access(request))


@api.get("/placements")
def placements(
    engine: Store,
    period: Literal["week", "month", "year", "custom"] = "month",
    start: unified.date | None = None,
    end: unified.date | None = None,
    company_id: UUID | None = None,
):
    return unified.report(engine, period, start, end, str(company_id) if company_id else None)


@api.get("/candidates/{candidate_id}/eligibility")
def candidate_eligibility(candidate_id: int, engine: Store):
    with engine.connect() as conn:
        one(conn, "candidates", candidate_id)
        return unified.eligibility(conn, candidate_id)


@api.post("/candidates/{candidate_id}/parsed-preview", dependencies=[Depends(same_origin)])
def preview_parse(candidate_id: int, data: unified.ParsedResumeInput, engine: Store):
    with engine.connect() as conn:
        return {
            "fields": unified.parsed_diff(one(conn, "candidates", candidate_id), data.profile),
            "saved": False,
        }


@api.post("/candidates/{candidate_id}/parsed-review", dependencies=[Depends(same_origin)])
def approve_parse(candidate_id: int, data: unified.ParsedReview, request: Request, engine: Store):
    return unified.review_parse(engine, candidate_id, data, access(request))


@api.post("/jobs/{job_id}/candidates/{link_id}/outcome", dependencies=[Depends(same_origin)])
def record_outcome(
    job_id: int, link_id: int, data: unified.Action, request: Request, engine: Store
):
    return unified.outcome(
        engine, job_id, link_id, data, access(request, supervisor=data.action == "REACTIVATE")
    )


@api.put("/jobs/{job_id}/contact", dependencies=[Depends(same_origin)])
def select_contact(job_id: int, data: unified.ContactChoice, request: Request, engine: Store):
    return unified.choose_contact(engine, job_id, data, access(request))


@api.get("/email-context")
def email_context(
    engine: Store,
    candidate_id: int = Query(ge=1),
    job_id: int = Query(ge=1),
    audience: Literal["CANDIDATE", "COMPANY"] = "CANDIDATE",
    contact_id: UUID | None = None,
    selected_stage: Stage | None = None,
    selected_round_id: str | None = Query(default=None, min_length=1, max_length=200),
):
    return unified.email_context(
        engine,
        candidate_id,
        job_id,
        audience,
        str(contact_id) if contact_id else None,
        selected_stage,
        selected_round_id,
    )


from .approved_router import router as approved_router  # noqa: E402

api.include_router(approved_router)
router.include_router(api)

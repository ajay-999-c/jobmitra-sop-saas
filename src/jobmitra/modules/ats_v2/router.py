"""Additive ATS endpoints; all SQLite entities use a distinct namespace and engine."""

from typing import Annotated, Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from jobmitra.core.pages import templates
from jobmitra.core.workflow import same_origin

from . import candidates, jobs, resumes, storage_diagnostics
from .candidate_schemas import (
    CandidateCreate,
    CandidatePatch,
    GenerateResumeInput,
    ParsedResumeInput,
    SearchParams,
)
from .common import AtsError, one
from .companies import CompanyGateway, resolve_companies
from .database import schema_version
from .schemas import (
    ActivityInput,
    ActivityPatch,
    FeedbackInput,
    JobCreate,
    JobPatch,
    LinkInput,
    MoveInput,
    WorkflowInput,
)


class AtsRoute(APIRoute):
    def __init__(self, *args, **kwargs):
        name = kwargs.get("name") or kwargs["endpoint"].__name__
        kwargs["name"] = name if name.startswith("ats_v2_") else "ats_v2_" + name
        super().__init__(*args, **kwargs)

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            from .request_receipts import request_key, set_key

            context_token = None
            diagnostic_token = storage_diagnostics.begin(request, self.path)
            try:
                context_token = set_key(request.headers.get("Idempotency-Key"))
                from .unified_access import guard_write

                guard_write(request)
                response = await original(request)
            except AtsError as error:
                if error.status == 503:
                    storage_diagnostics.emit(error)
                response = JSONResponse(
                    {
                        "detail": error.message,
                        **({"code": error.code} if error.code else {}),
                        **({"matches": error.matches} if error.matches is not None else {}),
                    },
                    status_code=error.status,
                )
            except (RequestValidationError, ValidationError) as error:
                from .validation_feedback import field_feedback

                response = JSONResponse(
                    {
                        "detail": "Check the required fields and valid values.",
                        "fields": [list(e["loc"]) for e in error.errors()],
                        "field_errors": field_feedback(error),
                    },
                    status_code=422,
                )
            except IntegrityError:
                response = JSONResponse(
                    {
                        "detail": "This change conflicts with existing records. "
                        "Reload and retry; no partial changes were saved."
                    },
                    status_code=409,
                )
            except (SQLAlchemyError, OSError) as error:
                storage_diagnostics.emit(error)
                response = JSONResponse(
                    {"detail": "ATS storage is unavailable. No change was confirmed."},
                    status_code=503,
                )
            finally:
                storage_diagnostics.end(diagnostic_token)
                if context_token is not None:
                    request_key.reset(context_token)
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                }
            )
            return response

        return handle


def enabled(request: Request):
    if not request.app.state.settings.ats_v2_enabled:
        raise HTTPException(404, "JD Workspace is not enabled.")


def ats_engine(request: Request):
    engine = getattr(request.app.state, "ats_v2_engine", None)
    if engine is None:
        raise AtsError(
            "Configure and initialize the separate ATS V2 SQLite database, then restart.", 503
        )
    return engine


def company_gateway(engine: Annotated[Engine, Depends(ats_engine)]):
    return CompanyGateway(engine)


Store = Annotated[Engine, Depends(ats_engine)]
Companies = Annotated[CompanyGateway, Depends(company_gateway)]
router = APIRouter(tags=["ATS V2"], route_class=AtsRoute, dependencies=[Depends(enabled)])
api = APIRouter(prefix="/api/ats-v2", route_class=AtsRoute)


def page(request, name):
    return templates.TemplateResponse(
        request=request,
        name=f"ats_v2/{name}.html",
        context={},
        headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        },
    )


@router.get("/jd-workspace-v2", include_in_schema=False)
def workspace_page(request: Request):
    return page(request, "workspace")


@router.get("/candidate-search-v2", include_in_schema=False)
@router.get(
    "/ats-v2/candidates/{candidate_id}",
    include_in_schema=False,
    name="ats_v2_candidate_profile_page",
)
def search_page(request: Request):
    return page(request, "search")


@api.get("/health")
def health(engine: Store):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        version = schema_version(conn)
    return {"status": "ok", "storage": engine.dialect.name, "schema": f"ats-v2-{version}"}


@api.get("/companies")
def company_options(gateway: Companies):
    return gateway.options()


@api.get("/companies/{company_id}")
def company_detail(company_id: str, gateway: Companies):
    return gateway.detail(company_id)


@api.get("/jobs")
def jobs_list(
    engine: Store,
    gateway: Companies,
    status: Literal["DRAFT", "ACTIVE", "ON_HOLD", "CLOSED"] | None = None,
    page: int = Query(1, ge=1, le=1000000),
    page_size: int = Query(50, ge=1, le=100),
):
    result = jobs.list_jobs(engine, status=status, page=page, page_size=page_size)
    result["company_error"] = resolve_companies(result["items"], gateway)
    return result


@api.get("/dashboard")
def dashboard(engine: Store):
    return jobs.list_jobs(engine, page_size=1)["summary"]


@api.post("/jobs", status_code=201, dependencies=[Depends(same_origin)])
def job_create(data: JobCreate, engine: Store, gateway: Companies):
    return jobs.create_job(engine, data, gateway)


@api.get("/jobs/{job_id}")
def job_detail(job_id: int, engine: Store, gateway: Companies):
    result = jobs.get_job(engine, job_id)
    result["company_error"] = resolve_companies([result], gateway)
    return result


@api.patch("/jobs/{job_id}", dependencies=[Depends(same_origin)])
def job_patch(job_id: int, data: JobPatch, engine: Store, gateway: Companies):
    return jobs.update_job(engine, job_id, data, gateway)


@api.get("/jobs/{job_id}/workflow")
def workflow_get(job_id: int, engine: Store):
    return jobs.get_workflow(engine, job_id)


@api.put("/jobs/{job_id}/workflow", dependencies=[Depends(same_origin)])
def workflow_save(job_id: int, data: WorkflowInput, engine: Store):
    return jobs.save_workflow(engine, job_id, data)


@api.get("/jobs/{job_id}/pipeline")
def pipeline_get(job_id: int, engine: Store):
    return jobs.pipeline(engine, job_id)


@api.post("/jobs/{job_id}/candidates", status_code=201, dependencies=[Depends(same_origin)])
def candidate_link(job_id: int, data: LinkInput, engine: Store):
    return jobs.associate(engine, job_id, data.candidate_id)


@api.post("/jobs/{job_id}/candidates/{link_id}/move", dependencies=[Depends(same_origin)])
def candidate_move(job_id: int, link_id: int, data: MoveInput, engine: Store):
    return jobs.move_candidate(engine, job_id, link_id, data)


@api.post("/jobs/{job_id}/candidates/{link_id}/feedback", dependencies=[Depends(same_origin)])
def candidate_feedback(job_id: int, link_id: int, data: FeedbackInput, engine: Store):
    return jobs.feedback(engine, job_id, link_id, data)


@api.get("/candidates")
def candidate_search(engine: Store, params: Annotated[SearchParams, Query()]):
    return candidates.search_candidates(engine, params)


@api.post("/candidates", status_code=201, dependencies=[Depends(same_origin)])
def candidate_create(data: CandidateCreate, engine: Store):
    return candidates.create_candidate(engine, data)


@api.get("/candidates/{candidate_id}")
def candidate_detail(candidate_id: int, engine: Store):
    return candidates.get_candidate(engine, candidate_id)


@api.patch("/candidates/{candidate_id}", dependencies=[Depends(same_origin)])
def candidate_patch(candidate_id: int, data: CandidatePatch, engine: Store):
    return candidates.update_candidate(engine, candidate_id, data)


@api.get("/candidates/{candidate_id}/resumes")
def resume_history(candidate_id: int, engine: Store):
    return resumes.list_resumes(engine, candidate_id)


@api.post(
    "/candidates/{candidate_id}/resumes", status_code=201, dependencies=[Depends(same_origin)]
)
async def resume_upload(
    candidate_id: int,
    request: Request,
    engine: Store,
    filename: Annotated[str, Header(alias="X-Resume-Filename")],
    kind: Annotated[
        Literal["ORIGINAL", "JOBMITRA_STANDARD"], Header(alias="X-Resume-Kind")
    ] = "ORIGINAL",
):
    settings = request.app.state.settings
    metadata = {}
    from .unified import is_v3

    with engine.connect() as conn:
        v3 = is_v3(conn)
    if v3:
        from .resume_inputs import ResumeMetadata
        from .unified_access import access

        raw = unquote(request.headers.get("X-Resume-Metadata", "{}"))
        if len(raw) > 8000:
            raise AtsError("Resume metadata is too large.")
        try:
            metadata = ResumeMetadata.model_validate_json(raw).model_dump(exclude_none=True)
        except ValueError:
            raise AtsError("Check preparation source, original link and upload notes.") from None
        metadata["actor_role"] = access(request)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > settings.resume_max_bytes:
            raise AtsError("Resume exceeds the configured upload limit.", 413)
        data.extend(chunk)
    if metadata and unquote(filename).lower().endswith(".pdf"):
        from .proposal_documents import validate_pdf

        validate_pdf(bytes(data), unquote(filename))
    result = await run_in_threadpool(
        resumes.upload_resume,
        engine,
        candidate_id,
        settings.ats_v2_resume_storage_root,
        bytes(data),
        unquote(filename),
        settings.resume_max_bytes,
        kind,
        metadata,
        request.headers.get("X-Resume-Reuse-Existing") == "1",
    )
    if result.get("reused_existing"):
        return JSONResponse(result, status_code=200)
    return result


@api.get("/candidates/{candidate_id}/resumes/{resume_id}/download")
def resume_download(candidate_id: int, resume_id: int, request: Request, engine: Store):
    from .unified import is_v3
    from .unified_access import access

    with engine.connect() as conn:
        if is_v3(conn):
            access(request)
    blob, media, filename = resumes.download_bytes(
        engine, candidate_id, resume_id, request.app.state.settings.ats_v2_resume_storage_root
    )
    from urllib.parse import quote

    return Response(
        blob,
        media_type=media,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
        },
    )


@api.get("/resumes/{resume_id}/download")
def resume_download_alias(resume_id: int, request: Request, engine: Store):
    with engine.connect() as conn:
        candidate_id = one(conn, "candidate_resumes", resume_id)["candidate_id"]
    return resume_download(candidate_id, resume_id, request, engine)


@api.post(
    "/candidates/{candidate_id}/parsed-resume", status_code=201, dependencies=[Depends(same_origin)]
)
def parsed_resume(candidate_id: int, data: ParsedResumeInput, engine: Store):
    return resumes.save_parsed_resume(engine, candidate_id, data)


@api.post(
    "/candidates/{candidate_id}/standardize", status_code=201, dependencies=[Depends(same_origin)]
)
def standardized_resume(
    candidate_id: int, data: GenerateResumeInput, request: Request, engine: Store
):
    return resumes.generate_resume(
        engine, candidate_id, request.app.state.settings.ats_v2_resume_storage_root, data
    )


@api.get("/candidates/{candidate_id}/activities")
def candidate_activities(candidate_id: int, engine: Store):
    return jobs.activities(engine, candidate_id)


@api.post(
    "/candidates/{candidate_id}/activities", status_code=201, dependencies=[Depends(same_origin)]
)
def activity_create(candidate_id: int, data: ActivityInput, engine: Store):
    return jobs.save_activity(engine, candidate_id, data)


@api.patch("/activities/{activity_id}", dependencies=[Depends(same_origin)])
def activity_patch(activity_id: int, data: ActivityPatch, engine: Store):
    with engine.connect() as conn:
        candidate_id = one(conn, "candidate_activities", activity_id)["candidate_id"]
    return jobs.save_activity(engine, candidate_id, data, activity_id)


@api.get("/history")
def history_get(
    engine: Store,
    candidate_id: int | None = Query(None, ge=1),
    job_id: int | None = Query(None, ge=1),
    jd_candidate_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1, le=1000000),
    page_size: int = Query(50, ge=1, le=100),
):
    return jobs.history(
        engine,
        candidate_id=candidate_id,
        job_id=job_id,
        jd_candidate_id=jd_candidate_id,
        page=page,
        page_size=page_size,
    )


router.include_router(api)


class AtsBodyLimit:
    """Cap new-module request bodies without changing legacy middleware behavior."""

    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not scope.get("path", "").startswith("/api/ats-v2/")
            or scope.get("method") not in {"POST", "PATCH", "PUT"}
        ):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        limit = (
            512000 if b"application/json" in headers.get(b"content-type", b"") else self.max_bytes
        )
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                return await JSONResponse(
                    {"detail": "Request exceeds the allowed size."}, status_code=413
                )(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

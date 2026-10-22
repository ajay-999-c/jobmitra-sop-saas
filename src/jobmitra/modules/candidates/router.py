"""Persistent Candidate Desk routes. File bytes never enter SQL or static assets."""

from datetime import date
from tempfile import SpooledTemporaryFile
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from jobmitra.core.pages import render
from jobmitra.core.workflow import Database, WorkflowError, office_today, optional_uuid, same_origin

from . import repository as repo
from .constants import STATES, UNION_TERRITORIES, DocumentKind
from .documents import CandidateDocumentService
from .foundit import (
    FounditCandidatePreview,
    FounditCreate,
    FounditPaste,
    FounditPatch,
    confirmed_identity,
    parse_foundit_text,
)
from .models import WorkDomain, WorkSubdomain
from .schemas import (
    CandidateCreate,
    CandidatePatch,
    CandidateRead,
    CatalogPatch,
    DocumentRead,
    DomainCreate,
    JobSearchRequestCreate,
    JobSearchRequestPatch,
    JobSearchRequestRead,
    ResumeParseCreate,
    ResumeParseRead,
    ResumeParseReview,
    SubdomainCreate,
    VisitCreate,
    VisitRead,
)
from .service import (
    CandidateService,
    DomainCatalogService,
    JobSearchService,
    ResumeParseService,
    VisitService,
)
from .storage import LocalDocumentStorage

router = APIRouter(tags=["Candidate Desk"])
WRITE = [Depends(same_origin)]


def storage(request):
    settings = request.app.state.settings
    try:
        return LocalDocumentStorage(settings.document_storage_root, settings.document_max_bytes)
    except OSError:
        raise WorkflowError("Private document storage is unavailable.", 503) from None


@router.get("/api/candidates", response_model=list[CandidateRead])
def candidates(session: Database, q: str | None = None):
    return CandidateService(session).search_candidates(q)


@router.get("/api/candidates/duplicates", response_model=list[CandidateRead])
def duplicates(
    session: Database,
    mobile: str | None = None,
    exclude_id: UUID | None = None,
    email: str | None = None,
):
    return CandidateService(session).find_possible_duplicates(mobile, exclude_id, email)


@router.post("/api/candidates", response_model=CandidateRead, status_code=201, dependencies=WRITE)
def create_candidate(data: CandidateCreate, session: Database):
    return CandidateService(session).create_candidate(data)


@router.post(
    "/api/candidates/foundit/preview", response_model=FounditCandidatePreview, dependencies=WRITE
)
def foundit_preview(data: FounditPaste):
    return parse_foundit_text(data.raw)


def check_foundit_identity(data):
    try:
        confirmed_identity(data)
    except ValueError as error:
        raise WorkflowError(str(error)) from None


@router.post(
    "/api/candidates/foundit/confirm",
    response_model=CandidateRead,
    status_code=201,
    dependencies=WRITE,
)
def foundit_create(data: FounditCreate, session: Database):
    check_foundit_identity(data)
    candidate = CandidateCreate.model_validate(data.model_dump(exclude={"confirmed"}))
    return CandidateService(session).create_candidate(candidate, strict_contacts=True)


@router.patch(
    "/api/candidates/foundit/{candidate_id}/confirm",
    response_model=CandidateRead,
    dependencies=WRITE,
)
def foundit_update(candidate_id: UUID, data: FounditPatch, session: Database):
    check_foundit_identity(data)
    change = CandidatePatch.model_validate(
        data.model_dump(exclude={"confirmed", "recorded_by_staff_id"}, exclude_unset=True)
    )
    return CandidateService(session).update_candidate(
        candidate_id, change, strict_contacts=True, actor=data.recorded_by_staff_id
    )


@router.get("/api/candidates/{candidate_id}", response_model=CandidateRead)
def candidate(candidate_id: UUID, session: Database):
    return CandidateService(session).get_candidate_detail(candidate_id)


@router.patch("/api/candidates/{candidate_id}", response_model=CandidateRead, dependencies=WRITE)
def edit_candidate(candidate_id: UUID, data: CandidatePatch, session: Database):
    return CandidateService(session).update_candidate(candidate_id, data)


@router.get("/api/office-visits", response_model=list[VisitRead])
def visits(
    request: Request, session: Database, day: date | None = None, candidate_id: UUID | None = None
):
    return VisitService(session, request.app.state.settings.office_timezone).list_visits_for_day(
        day, candidate_id
    )


@router.post(
    "/api/candidates/{candidate_id}/visits",
    response_model=VisitRead,
    status_code=201,
    dependencies=WRITE,
)
def record_visit(candidate_id: UUID, data: VisitCreate, session: Database):
    return VisitService(session).record_visit(candidate_id, data)


@router.get("/api/job-search-requests", response_model=list[JobSearchRequestRead])
def searches(
    request: Request,
    session: Database,
    staff_id: UUID | None = None,
    due_only: bool = False,
    candidate_id: UUID | None = None,
):
    return JobSearchService(session, request.app.state.settings.office_timezone).list_due_requests(
        staff_id, due_only, candidate_id
    )


@router.post(
    "/api/candidates/{candidate_id}/job-search",
    response_model=JobSearchRequestRead,
    status_code=201,
    dependencies=WRITE,
)
def create_search(candidate_id: UUID, data: JobSearchRequestCreate, session: Database):
    return JobSearchService(session).create_request(candidate_id, data)


@router.patch(
    "/api/job-search-requests/{identity}", response_model=JobSearchRequestRead, dependencies=WRITE
)
def edit_search(identity: UUID, data: JobSearchRequestPatch, session: Database):
    return JobSearchService(session).update_request(identity, data)


@router.get("/api/domains")
def catalog(session: Database, active: bool = True):
    return DomainCatalogService(session).list_active_catalog(active)


@router.post("/api/domains", status_code=201, dependencies=WRITE)
def add_domain(data: DomainCreate, session: Database):
    return DomainCatalogService(session).add_domain(data)


@router.post("/api/subdomains", status_code=201, dependencies=WRITE)
def add_subdomain(data: SubdomainCreate, session: Database):
    return DomainCatalogService(session).add_subdomain(data)


@router.patch("/api/domains/{identity}", dependencies=WRITE)
def edit_domain(identity: UUID, data: CatalogPatch, session: Database):
    return DomainCatalogService(session).update_category(WorkDomain, identity, data)


@router.patch("/api/subdomains/{identity}", dependencies=WRITE)
def edit_subdomain(identity: UUID, data: CatalogPatch, session: Database):
    return DomainCatalogService(session).update_category(WorkSubdomain, identity, data)


@router.get("/api/candidates/{candidate_id}/documents", response_model=list[DocumentRead])
def list_documents(candidate_id: UUID, session: Database):
    return [DocumentRead.model_validate(row) for row in repo.documents(session, candidate_id)]


@router.post(
    "/api/candidates/{candidate_id}/documents",
    response_model=DocumentRead,
    status_code=201,
    dependencies=WRITE,
)
async def upload_document(
    candidate_id: UUID,
    request: Request,
    session: Database,
    filename: Annotated[str, Header(alias="X-Document-Filename")],
    kind: DocumentKind,
    staff_id: UUID | None = None,
    source_document_id: UUID | None = None,
    reviewed: bool = False,
):
    filename = unquote(filename)
    store = storage(request)
    total = 0
    # Bounded streaming before parsing a document; no multipart dependency needed.
    with SpooledTemporaryFile(max_size=1048576, mode="w+b") as stream:
        async for chunk in request.stream():
            total += len(chunk)
            if total > request.app.state.settings.document_max_bytes:
                raise WorkflowError("File exceeds the configured upload limit.", 413)
            stream.write(chunk)
        stream.seek(0)
        try:
            return await run_in_threadpool(
                CandidateDocumentService(session, store).upload_document,
                candidate_id,
                stream,
                filename,
                kind,
                staff_id,
                source_document_id,
                reviewed,
            )
        except OSError:
            raise WorkflowError("Document storage failed; upload was not confirmed.", 503) from None


@router.get("/candidates/{candidate_id}/documents/{document_id}/download")
def download(candidate_id: UUID, document_id: UUID, request: Request, session: Database):
    doc, path = CandidateDocumentService(session, storage(request)).download_document(
        candidate_id, document_id
    )
    return FileResponse(
        path,
        media_type=doc.content_type,
        filename=doc.original_filename,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.get("/api/candidates/{candidate_id}/resume-parses", response_model=list[ResumeParseRead])
def list_parses(candidate_id: UUID, session: Database):
    return ResumeParseService(session).list_parse_results(candidate_id)


@router.post(
    "/api/candidates/{candidate_id}/resume-parses",
    response_model=ResumeParseRead,
    status_code=201,
    dependencies=WRITE,
)
def paste_parse(candidate_id: UUID, data: ResumeParseCreate, session: Database):
    return ResumeParseService(session).add_parse_result(candidate_id, data)


@router.patch(
    "/api/candidates/{candidate_id}/resume-parses/{identity}",
    response_model=ResumeParseRead,
    dependencies=WRITE,
)
def review_parse(candidate_id: UUID, identity: UUID, data: ResumeParseReview, session: Database):
    return ResumeParseService(session).review_parse_result(candidate_id, identity, data)


def page(request, session, name, **context):
    return render(request, session, name, template_group="candidates", **context)


def form_context(session):
    return {
        "catalog": DomainCatalogService(session).list_active_catalog(False),
        "roles": repo.roles(session),
        "states": STATES,
        "territories": UNION_TERRITORIES,
    }


@router.get("/candidates", include_in_schema=False)
def directory(request: Request, session: Database, q: str | None = None):
    rows = CandidateService(session).search_candidates(q)
    name = "candidate_rows" if request.headers.get("hx-request") == "true" else "directory"
    return page(request, session, name, rows=rows, q=q or "", **form_context(session))


@router.get("/candidates/new", include_in_schema=False)
def new_candidate(request: Request, session: Database, walkin: bool = False):
    return page(request, session, "new", walkin=walkin, **form_context(session))


@router.get("/candidates/foundit-import", include_in_schema=False)
def foundit_import(request: Request, session: Database):
    return page(request, session, "foundit", **form_context(session))


@router.get("/candidates/{candidate_id}", include_in_schema=False)
def profile(candidate_id: UUID, request: Request, session: Database):
    candidate = CandidateService(session).get_candidate_detail(candidate_id)
    return page(
        request,
        session,
        "profile",
        candidate=candidate,
        visits=VisitService(session).list_visits_for_day(candidate_id=candidate_id),
        searches=JobSearchService(session).list_candidate_requests(candidate_id),
        documents=[
            DocumentRead.model_validate(row) for row in repo.documents(session, candidate_id)
        ],
        parses=ResumeParseService(session).list_parse_results(candidate_id),
        **form_context(session),
    )


@router.get("/candidate-desk", include_in_schema=False)
def today(request: Request, session: Database):
    day = office_today(request.app.state.settings.office_timezone)
    return page(
        request,
        session,
        "today",
        day=day,
        visits=VisitService(
            session, request.app.state.settings.office_timezone
        ).list_visits_for_day(day),
        searches=JobSearchService(
            session, request.app.state.settings.office_timezone
        ).list_due_requests(due_only=True),
        people=CandidateService(session).search_candidates(),
    )


@router.get("/office-visits", include_in_schema=False)
def visit_page(request: Request, session: Database, day: str | None = None):
    try:
        day = date.fromisoformat(day) if day else None
    except ValueError:
        raise WorkflowError("Choose a valid visit date.") from None
    return page(
        request,
        session,
        "visits",
        visits=VisitService(
            session, request.app.state.settings.office_timezone
        ).list_visits_for_day(day),
        day=day,
        people=CandidateService(session).search_candidates(),
    )


@router.get("/job-search-requests", include_in_schema=False)
def request_page(
    request: Request, session: Database, staff_id: str | None = None, due_only: bool = False
):
    staff_id = optional_uuid(staff_id)
    return page(
        request,
        session,
        "requests",
        searches=JobSearchService(
            session, request.app.state.settings.office_timezone
        ).list_due_requests(staff_id, due_only),
        people=CandidateService(session).search_candidates(),
    )


@router.get("/domains", include_in_schema=False)
def domain_page(request: Request, session: Database):
    return page(
        request,
        session,
        "domains",
        catalog=DomainCatalogService(session).list_active_catalog(False),
    )

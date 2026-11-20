"""Private JSON/PDF parse workflow, independent of processor identities and external AI."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from jobmitra.core.workflow import same_origin

from . import parsed_documents as documents
from .router import AtsRoute
from .unified_access import access
from .unified_router import Store

router = APIRouter(prefix="/candidates/{candidate_id}", route_class=AtsRoute)


@router.post("/parsed-drafts", status_code=201, dependencies=[Depends(same_origin)])
def draft(candidate_id: int, data: documents.JsonDraft, request: Request, engine: Store):
    return documents.json_draft(
        engine,
        candidate_id,
        data,
        access(request),
        request.app.state.settings.ats_v2_resume_storage_root,
    )


@router.post("/resumes/{resume_id}/extract", status_code=201, dependencies=[Depends(same_origin)])
def extract(
    candidate_id: int, resume_id: int, data: documents.Extract, request: Request, engine: Store
):
    return documents.extract(
        engine,
        candidate_id,
        resume_id,
        data,
        access(request),
        request.app.state.settings.ats_v2_resume_storage_root,
    )


@router.get("/parsed-drafts/{draft_id}")
def details(candidate_id: int, draft_id: int, request: Request, engine: Store):
    access(request)
    return documents.get(engine, candidate_id, draft_id)


@router.get("/parsed-drafts/{draft_id}/download")
def download(candidate_id: int, draft_id: int, request: Request, engine: Store):
    access(request)
    return Response(
        documents.download(engine, candidate_id, draft_id),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="parsed-resume-{draft_id}.json"'},
    )


@router.post("/parsed-drafts/{draft_id}/approve", dependencies=[Depends(same_origin)])
def approve(
    candidate_id: int, draft_id: int, data: documents.Approval, request: Request, engine: Store
):
    return documents.approve(engine, candidate_id, draft_id, data, access(request))


@router.get("/resumes/{resume_id}/preview")
def preview(candidate_id: int, resume_id: int, request: Request, engine: Store):
    access(request)
    _, blob, _ = documents._source(
        engine,
        candidate_id,
        resume_id,
        request.app.state.settings.ats_v2_resume_storage_root,
        pdf=True,
    )
    return Response(
        blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="altered-resume-{resume_id}.pdf"',
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )

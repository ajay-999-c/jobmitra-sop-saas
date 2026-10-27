"""Optional resumes: candidate-scoped originals, no parser or profile mutations."""

from datetime import datetime
from tempfile import SpooledTemporaryFile
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy import select, update
from starlette.concurrency import run_in_threadpool

from jobmitra.core.workflow import Database, WorkflowError, same_origin

from .models import Candidate, CandidateResume
from .service import required
from .storage import PDF, LocalDocumentStorage


class ResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    candidate_id: UUID
    original_filename: str
    mime_type: str
    file_size: int
    file_hash: str
    parsed_json: dict | None
    parsing_status: str
    parsing_error: str | None
    is_active: bool
    uploaded_at: datetime
    updated_at: datetime

    @field_serializer("parsing_error")
    def public_parsing_error(self, value):
        # Future parser diagnostics may contain file paths or provider details.
        return "Parsing failed. Contact your administrator." if value else None


# Keep resume routes grouped so a future application-wide dependency can protect them.
router = APIRouter(tags=["Candidate resumes"])


def resume_storage(request):
    settings = request.app.state.settings
    try:
        return LocalDocumentStorage(settings.document_storage_root, settings.resume_max_bytes)
    except OSError:
        raise WorkflowError("Private resume storage is unavailable.", 503) from None


class ResumeService:
    def __init__(self, session, storage):
        self.session, self.storage = session, storage

    def upload(self, candidate_id, stream, filename):
        stored = None
        try:
            with self.session.begin():
                # Serialize all version changes for a candidate, including first upload.
                required(self.session, Candidate, candidate_id, True)
                stored = self.storage.save(stream, filename)
                self.session.execute(
                    update(CandidateResume)
                    .where(
                        CandidateResume.candidate_id == candidate_id,
                        CandidateResume.is_active.is_(True),
                    )
                    .values(is_active=False)
                )
                row = CandidateResume(
                    candidate_id=candidate_id,
                    original_filename=filename,
                    storage_key=stored.storage_key,
                    mime_type=stored.content_type,
                    file_size=stored.size_bytes,
                    file_hash=stored.sha256,
                )
                self.session.add(row)
                self.session.flush()
                result = ResumeRead.model_validate(row)
            return result
        except BaseException:
            if stored is not None:
                self.storage.remove(stored.storage_key)
            raise

    def original(self, candidate_id, resume_id):
        """Future parsers can resolve original bytes by resume ID without altering them."""
        row = self.session.scalar(
            select(CandidateResume).where(
                CandidateResume.id == resume_id,
                CandidateResume.candidate_id == candidate_id,
            )
        )
        if row is None:
            raise WorkflowError("Resume not found.", 404)
        path = self.storage.path(row.storage_key)
        if not path.is_file():
            raise WorkflowError("Original resume file is unavailable.", 404)
        return row, path


@router.get("/api/candidates/{candidate_id}/resumes", response_model=list[ResumeRead])
def history(candidate_id: UUID, session: Database):
    required(session, Candidate, candidate_id)
    return session.scalars(
        select(CandidateResume)
        .where(
            CandidateResume.candidate_id == candidate_id,
        )
        .order_by(CandidateResume.uploaded_at.desc(), CandidateResume.id)
    ).all()


@router.post(
    "/api/candidates/{candidate_id}/resumes",
    response_model=ResumeRead,
    status_code=201,
    dependencies=[Depends(same_origin)],
)
async def upload(
    candidate_id: UUID,
    request: Request,
    session: Database,
    filename: Annotated[str, Header(alias="X-Document-Filename")],
):
    store = resume_storage(request)
    total = 0
    try:
        with SpooledTemporaryFile(max_size=1048576, mode="w+b") as stream:
            async for chunk in request.stream():
                total += len(chunk)
                if total > request.app.state.settings.resume_max_bytes:
                    raise WorkflowError("Resume exceeds the configured upload limit.", 413)
                stream.write(chunk)
            stream.seek(0)
            return await run_in_threadpool(
                ResumeService(session, store).upload, candidate_id, stream, unquote(filename)
            )
    except OSError:
        raise WorkflowError("Resume storage failed; upload was not confirmed.", 503) from None


@router.get("/api/candidates/{candidate_id}/resumes/{resume_id}/download")
@router.get("/api/candidates/{candidate_id}/resumes/{resume_id}/preview")
def original(candidate_id: UUID, resume_id: UUID, request: Request, session: Database):
    row, path = ResumeService(session, resume_storage(request)).original(candidate_id, resume_id)
    preview = request.url.path.endswith("/preview") and row.mime_type == PDF
    return FileResponse(
        path,
        filename=row.original_filename,
        media_type=row.mime_type,
        content_disposition_type="inline" if preview else "attachment",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )

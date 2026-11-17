"""Explicitly enabled localhost resume demo; no PostgreSQL dependencies."""

import sqlite3
import threading
from ipaddress import ip_address
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from jobmitra.core.pages import templates
from jobmitra.core.workflow import same_origin

from .service import Processor
from .store import ProcessingError, database, status

creation_lock = threading.Lock()
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


class SafeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(
                    {"detail": "Check the candidate details and required confirmations."},
                    status_code=422,
                )
            except ProcessingError as error:
                response = JSONResponse({"detail": error.message}, status_code=error.status)
            except (sqlite3.Error, OSError, ValueError):
                response = JSONResponse(
                    {"detail": "Local processor storage is unavailable or needs review."},
                    status_code=503,
                )
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                }
            )
            return response

        return handle


def local_access(request: Request):
    if not request.app.state.settings.resume_processing_enabled:
        raise HTTPException(404, "Resume Processing is not enabled.")
    try:
        peer = ip_address(request.client.host) if request.client else None
    except ValueError:
        peer = None
    if (
        not peer
        or not peer.is_loopback
        or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(403, "Resume Processing demo is available on localhost only.")
    return "local-demo-unverified"


def processor(request: Request):
    with creation_lock:
        if not hasattr(request.app.state, "resume_processor"):
            request.app.state.resume_processor = Processor(request.app.state.settings)
    return request.app.state.resume_processor


LocalActor = Annotated[str, Depends(local_access)]
Service = Annotated[Processor, Depends(processor)]
router = APIRouter(
    tags=["Resume Processing"], route_class=SafeRoute, dependencies=[Depends(local_access)]
)


class CandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str = Field(min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    mobile: str | None = Field(default=None, max_length=30)
    candidate_id: UUID | None = None
    consent: bool

    @field_validator("full_name")
    @classmethod
    def name(cls, value):
        value = " ".join(value.split())
        if len(value) < 2 or any(c.isdigit() or c in "<>[]{}@" or ord(c) < 32 for c in value):
            raise ValueError("Enter the candidate's full name.")
        return value

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        import re

        if not value:
            return None
        value = value.lower()
        if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", value):
            raise ValueError("Invalid email.")
        return value

    @field_validator("mobile")
    @classmethod
    def mobile_number(cls, value):
        import re

        if not value:
            return None
        value = re.sub(r"[\s()\-]", "", value)
        if re.fullmatch(r"[6-9]\d{9}", value):
            value = "+91" + value
        if not re.fullmatch(r"\+91[6-9]\d{9}", value):
            raise ValueError("Use a valid Indian mobile number.")
        return value

    @field_validator("consent")
    @classmethod
    def authorization(cls, value):
        if not value:
            raise ValueError("Candidate authorization is required.")
        return value


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parse_id: UUID
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved: bool
    facts_reviewed: bool

    @field_validator("facts_reviewed")
    @classmethod
    def reviewed(cls, value):
        if not value:
            raise ValueError("Review the source facts first.")
        return value


@router.get("/resume-processing", include_in_schema=False)
def page(request: Request, actor: LocalActor):
    return templates.TemplateResponse(
        request=request,
        name="resume_processing/studio.html",
        context={"staff": []},
        headers={"Content-Security-Policy": CSP},
    )


@router.get("/api/resume-processing/health")
def health(service: Service):
    with database(service.db):
        return {"status": "ok", "storage": "sqlite", "single_job": True}


@router.get("/api/resume-processing/candidates")
def candidates(service: Service):
    return service.candidates()


@router.post("/api/resume-processing/candidates", dependencies=[Depends(same_origin)])
def register(values: CandidateInput, service: Service):
    return service.register(values)


@router.post(
    "/api/resume-processing/candidates/{candidate_id}/documents",
    dependencies=[Depends(same_origin)],
)
async def upload(candidate_id: UUID, request: Request, service: Service, actor: LocalActor):
    data = await request.body()
    kind = request.headers.get("x-resume-format", "").lower()
    location = unquote(request.headers.get("x-candidate-location", ""))
    if len(location) > 120 or any(ord(c) < 32 for c in location):
        raise ProcessingError("Location must be a city or state within 120 characters.", 422)
    return await run_in_threadpool(
        service.upload,
        str(candidate_id),
        data,
        kind,
        consent=request.headers.get("x-candidate-consent") == "confirmed",
        location=location,
        actor=actor,
    )


@router.get("/api/resume-processing/documents")
def documents(service: Service):
    return service.documents()


@router.get("/api/resume-processing/documents/{doc_id}")
def document_status(doc_id: str, service: Service):
    with database(service.db) as conn:
        return status(conn, doc_id)


@router.post(
    "/api/resume-processing/documents/{doc_id}/process",
    dependencies=[Depends(same_origin)],
    status_code=202,
)
def process(doc_id: str, service: Service):
    return service.start(doc_id, "process")


@router.get("/api/resume-processing/documents/{doc_id}/review")
def preview(doc_id: str, service: Service):
    with database(service.db) as conn:
        status(conn, doc_id)  # Validate ID/ownership before passing it to the bridge.
    return service.review(doc_id)


@router.post(
    "/api/resume-processing/documents/{doc_id}/review", dependencies=[Depends(same_origin)]
)
def review(doc_id: str, values: ReviewInput, service: Service, actor: LocalActor):
    return service.approve(doc_id, values, actor)


@router.post(
    "/api/resume-processing/documents/{doc_id}/exports",
    dependencies=[Depends(same_origin)],
    status_code=202,
)
def exports(doc_id: str, service: Service):
    return service.start(doc_id, "export")


@router.get("/api/resume-processing/documents/{doc_id}/downloads/{kind}")
def download(doc_id: str, kind: str, service: Service):
    path = service.download(doc_id, kind)
    media = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "html": "text/html",
    }[path.suffix.lower().lstrip(".")]
    headers = {
        "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; "
        "img-src data:; base-uri 'none'; form-action 'none'"
    }
    return FileResponse(
        path,
        media_type=media,
        filename=f"Jobmitra_{doc_id[:12]}_{kind}{path.suffix}",
        content_disposition_type="inline" if kind in {"preview", "original"} else "attachment",
        headers=headers,
    )


class ResumeBodyLimit:
    """Bound this module's JSON and raw uploads before FastAPI consumes request bodies."""

    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not scope.get("path", "").startswith("/api/resume-processing/")
            or scope.get("method") not in {"POST", "PUT", "PATCH"}
        ):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        limit = (
            16 * 1024
            if b"application/json" in headers.get(b"content-type", b"")
            else self.max_bytes
        )
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                return await JSONResponse(
                    {"detail": "Request exceeds the allowed size."}, status_code=413
                )(scope, receive, send)
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

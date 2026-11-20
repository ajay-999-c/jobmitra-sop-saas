"""Company-scoped private PDF APIs. No automatic delivery or acceptance."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from jobmitra.core.pages import templates
from jobmitra.core.workflow import same_origin

from . import proposal, unified
from . import proposal_documents as documents
from .router import AtsRoute
from .unified_access import access
from .unified_router import Store


class ProposalRoute(AtsRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            if request.method == "POST":
                # Bound streamed JSON before FastAPI/base64 parsing, including chunked uploads.
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 14_100_000:
                        return JSONResponse({"detail": "Proposal request exceeds 14.1 MB."}, 413)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            return await original(request)

        return handle


router = APIRouter(prefix="/companies/{company_id}", route_class=ProposalRoute)


def guard(request, engine):
    role = access(request)
    documents.ready(engine, request.app.state.settings)
    return role, request.app.state.settings.unified_v12_proposal_storage_root


@router.get("/proposal-workspace", include_in_schema=False)
def workspace(company_id: UUID, request: Request, engine: Store):
    proposal.context(engine, str(company_id))
    return templates.TemplateResponse(
        request=request,
        name="v12/proposal.html",
        context={"company_id": str(company_id), "today": unified.office_today().isoformat()},
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
            "style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'self'; form-action 'self'",
        },
    )


@router.get("/proposals")
def history(company_id: UUID, request: Request, engine: Store):
    guard(request, engine)
    return documents.history(engine, str(company_id))


@router.post("/proposals", status_code=201, dependencies=[Depends(same_origin)])
def generate(company_id: UUID, data: documents.Generate, request: Request, engine: Store):
    role, root = guard(request, engine)
    return documents.generate(engine, str(company_id), data, role, root)


@router.get("/proposals/{proposal_id}/pdf")
def pdf(
    company_id: UUID, proposal_id: UUID, request: Request, engine: Store, download: bool = False
):
    _, root = guard(request, engine)
    blob = documents.document(engine, str(company_id), str(proposal_id), root)
    return Response(
        blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": ("attachment" if download else "inline")
            + f'; filename="Jobmitra-Proposal-{proposal_id}.pdf"',
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/proposals/{proposal_id}/email")
def email(company_id: UUID, proposal_id: UUID, request: Request, engine: Store):
    guard(request, engine)
    return documents.email(engine, str(company_id), str(proposal_id))


@router.post(
    "/proposals/{proposal_id}/signed-documents",
    status_code=201,
    dependencies=[Depends(same_origin)],
)
def upload(
    company_id: UUID,
    proposal_id: UUID,
    data: documents.SignedUpload,
    request: Request,
    engine: Store,
):
    role, root = guard(request, engine)
    return documents.upload_signed(engine, str(company_id), str(proposal_id), data, role, root)


@router.get("/proposals/{proposal_id}/signed-documents/{signed_id}")
def signed(company_id: UUID, proposal_id: UUID, signed_id: UUID, request: Request, engine: Store):
    _, root = guard(request, engine)
    blob = documents.document(engine, str(company_id), str(proposal_id), root, str(signed_id))
    return Response(
        blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="Signed-Jobmitra-Proposal-{signed_id}.pdf"'
            ),
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/proposals/{proposal_id}/status", dependencies=[Depends(same_origin)])
def status(
    company_id: UUID,
    proposal_id: UUID,
    data: documents.StatusChange,
    request: Request,
    engine: Store,
):
    role, _ = guard(request, engine)
    return documents.set_status(engine, str(company_id), str(proposal_id), data, role)

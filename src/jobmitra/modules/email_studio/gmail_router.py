"""Sending is explicit, Mac-only and direct-loopback-only, even in Office LAN mode."""

from fastapi import APIRouter, Depends, Request

from jobmitra.core.local_v12 import loopback
from jobmitra.core.workflow import same_origin
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.router import AtsRoute
from jobmitra.modules.ats_v2.unified_router import Store

from . import gmail_history as audit
from . import gmail_service as gmail

router = APIRouter(prefix="/api/v12/gmail", route_class=AtsRoute)


def local_request(request: Request):
    settings = request.app.state.settings
    if not settings.gmail_enabled:
        raise AtsError("Gmail sending is disabled.", 403)
    gmail.validate_configuration(settings)
    server, client = request.scope.get("server"), request.scope.get("client")
    if not (
        server
        and client
        and loopback(server[0])
        and loopback(client[0])
        and loopback(request.url.hostname)
        and not any(h == "forwarded" or h.startswith("x-forwarded-") for h in request.headers)
    ):
        raise AtsError("Gmail sending requires direct loopback access on the authorized Mac.", 403)


@router.get("/status")
def status(request: Request):
    if not request.app.state.settings.gmail_enabled:
        return {"status": "Gmail Disabled", "enabled": False}
    local_request(request)
    return gmail.connection_status(request.app.state.settings)


@router.get("/context/{candidate_id}", dependencies=[Depends(local_request)])
def recipient_context(candidate_id: int, request: Request, engine: Store):
    with engine.connect() as conn:
        return audit.recipient_context(conn, request.app.state.settings, candidate_id)


@router.post("/send", dependencies=[Depends(local_request), Depends(same_origin)])
def send_email(data: audit.SendInput, request: Request, engine: Store):
    if request.headers.get("Idempotency-Key") != str(data.reference):
        raise AtsError("The send reference and Idempotency-Key must match.")
    try:
        return audit.dispatch(engine, request.app.state.settings, data)
    except gmail.GmailError as error:
        raise AtsError(error.reason, 422) from None


@router.get("/history/{candidate_id}", dependencies=[Depends(local_request)])
def history(candidate_id: int, engine: Store):
    with engine.connect() as conn:
        return {"items": [audit.public(e) for e in audit.history(conn, candidate_id)]}

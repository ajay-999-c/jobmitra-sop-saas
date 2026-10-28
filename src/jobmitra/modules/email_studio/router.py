"""Serve the finalized standalone email tools verbatim; no database dependencies."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from jobmitra.core.pages import templates

router = APIRouter(tags=["Email"])
PROJECT_ROOT = Path(__file__).resolve().parents[4]
UPDATES_FILE = PROJECT_ROOT / "Jobmitra_Email_Studio_Technical_Interview_Simplified.html"
PROPOSAL_FILE = PROJECT_ROOT / "Jobmitra_Company_Proposal_Final.html"
SUBMISSION_FILE = PROJECT_ROOT / "Jobmitra_candidate_submission_final (1).html"


@router.get("/email", include_in_schema=False)
def email_home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="email_studio/index.html",
        context={"staff": []},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/email/updates", include_in_schema=False)
def candidate_updates():
    return FileResponse(UPDATES_FILE, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.get("/email/submission", include_in_schema=False)
def candidate_submission():
    return FileResponse(
        SUBMISSION_FILE, media_type="text/html", headers={"Cache-Control": "no-store"}
    )


@router.get("/email/proposal", include_in_schema=False)
def company_proposal():
    return FileResponse(
        PROPOSAL_FILE, media_type="text/html", headers={"Cache-Control": "no-store"}
    )

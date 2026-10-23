"""Browser-only resume editing; no candidate persistence endpoints."""

from fastapi import APIRouter, Request

from jobmitra.core.pages import render
from jobmitra.core.workflow import Database

router = APIRouter(tags=["Alter Resumes"])


@router.get("/alter-resumes", include_in_schema=False)
def resume_studio(request: Request, session: Database):
    return render(request, session, "studio", template_group="alter_resumes")

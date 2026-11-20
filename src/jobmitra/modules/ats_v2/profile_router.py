"""Authorized native Candidate Desk profile/Foundit services."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from jobmitra.core.workflow import same_origin

from . import candidate_profiles as profiles
from . import foundit_intake, resumes
from .resume_inputs import CurrentResume
from .router import AtsRoute
from .unified_access import access
from .unified_router import Store

router = APIRouter(route_class=AtsRoute)


@router.get("/candidates/{candidate_id}/profile")
def profile(candidate_id: int, request: Request, engine: Store):
    access(request)
    return profiles.get(engine, candidate_id)


@router.patch("/candidates/{candidate_id}/profile", dependencies=[Depends(same_origin)])
def edit(candidate_id: int, data: profiles.Review, request: Request, engine: Store):
    return profiles.save(engine, candidate_id, data, access(request))


@router.get("/candidates/{candidate_id}/profile-history")
def history(candidate_id: int, request: Request, engine: Store):
    access(request)
    profiles.get(engine, candidate_id)
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT "
                    "id,created_at,actor_name,actor_role,before_json,after_json,provenance_json "
                    "FROM candidate_profile_versions WHERE candidate_id=:id ORDER BY id DESC"
                ),
                {"id": candidate_id},
            ).mappings()
        ]


@router.post("/foundit/preview", dependencies=[Depends(same_origin)])
def preview(data: foundit_intake.Paste, request: Request, engine: Store):
    access(request)
    return foundit_intake.preview(engine, data.raw)


@router.post("/foundit/candidates", status_code=201, dependencies=[Depends(same_origin)])
def register(data: profiles.Intake, request: Request, engine: Store):
    return profiles.intake(engine, data, access(request))


@router.post(
    "/candidates/{candidate_id}/resumes/{resume_id}/current", dependencies=[Depends(same_origin)]
)
def current(
    candidate_id: int, resume_id: int, data: CurrentResume, request: Request, engine: Store
):
    role = access(request)
    # Verify actual bytes before designating an old version current.
    resumes.download_resume(
        engine, candidate_id, resume_id, request.app.state.settings.ats_v2_resume_storage_root
    )
    return resumes.set_current(
        engine, candidate_id, resume_id, data.expected_current_id, data.actor_name, role
    )

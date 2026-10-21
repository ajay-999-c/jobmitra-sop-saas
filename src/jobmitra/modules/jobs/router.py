from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from jobmitra.core.pages import render
from jobmitra.core.workflow import Database, WorkflowError, office_today, optional_uuid, same_origin
from jobmitra.modules.companies.repository import directory as company_directory
from jobmitra.modules.jobs import repository
from jobmitra.modules.jobs.focus import FOCUS_LABELS, FOCUS_STAGES
from jobmitra.modules.jobs.schemas import (
    ATSUpdate,
    JobCreate,
    JobPatch,
    JobRead,
    RecordedAction,
    RecruiterUpdate,
    Status,
    StatusPatch,
    TargetPatch,
    WorkFocusPatch,
)
from jobmitra.modules.jobs.service import JobRequirementService
from jobmitra.modules.worklog.service import ActivityService, TaskService

router = APIRouter(tags=["Requirements"])


def jobs(request, session):
    return JobRequirementService(session, request.app.state.settings.office_timezone)


@router.get("/api/jobs")
def list_jobs(
    request: Request,
    session: Database,
    q: str | None = None,
    status: Status | None = None,
    recruiter_id: UUID | None = None,
    domain: str | None = None,
    skill: str | None = None,
):
    return jobs(request, session).list_jobs(
        q=q, status=status, recruiter_id=recruiter_id, domain=domain, skill=skill
    )


@router.post(
    "/api/jobs", response_model=JobRead, status_code=201, dependencies=[Depends(same_origin)]
)
def create_job(data: JobCreate, request: Request, session: Database):
    return jobs(request, session).create_job(data)


@router.get("/api/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: UUID, request: Request, session: Database):
    return jobs(request, session).get_job_detail(job_id)


@router.patch("/api/jobs/{job_id}", response_model=JobRead, dependencies=[Depends(same_origin)])
def edit_job(job_id: UUID, data: JobPatch, request: Request, session: Database):
    return jobs(request, session).update_manual_criteria(job_id, data)


@router.put(
    "/api/jobs/{job_id}/recruiters", response_model=JobRead, dependencies=[Depends(same_origin)]
)
def recruiters(job_id: UUID, data: RecruiterUpdate, request: Request, session: Database):
    return jobs(request, session).set_recruiters(job_id, data)


@router.patch(
    "/api/jobs/{job_id}/work-focus", response_model=JobRead, dependencies=[Depends(same_origin)]
)
def work_focus(job_id: UUID, data: WorkFocusPatch, request: Request, session: Database):
    return jobs(request, session).change_work_focus(job_id, data)


@router.patch(
    "/api/jobs/{job_id}/target", response_model=JobRead, dependencies=[Depends(same_origin)]
)
def target(job_id: UUID, data: TargetPatch, request: Request, session: Database):
    return jobs(request, session).change_target(job_id, data)


@router.patch(
    "/api/jobs/{job_id}/status", response_model=JobRead, dependencies=[Depends(same_origin)]
)
def status(job_id: UUID, data: StatusPatch, request: Request, session: Database):
    return jobs(request, session).change_status(job_id, data)


@router.put(
    "/api/jobs/{job_id}/ats-json", response_model=JobRead, dependencies=[Depends(same_origin)]
)
def ats(job_id: UUID, data: ATSUpdate, request: Request, session: Database):
    return jobs(request, session).save_ats_json(job_id, data)


@router.post(
    "/api/jobs/{job_id}/shortlist-completion",
    response_model=JobRead,
    dependencies=[Depends(same_origin)],
)
def shortlist(job_id: UUID, data: RecordedAction, request: Request, session: Database):
    return jobs(request, session).confirm_shortlist(job_id, data)


@router.get("/overview", include_in_schema=False)
def overview(request: Request, session: Database):
    today = office_today(request.app.state.settings.office_timezone)
    return render(
        request,
        session,
        "overview",
        counts=repository.status_counts(session),
        rows=jobs(request, session).list_jobs(through=today + timedelta(days=3)),
    )


@router.get("/requirements", include_in_schema=False)
def requirement_directory(
    request: Request,
    session: Database,
    q: str | None = None,
    status: str | None = None,
    recruiter_id: str | None = None,
    domain: str | None = None,
    skill: str | None = None,
):
    status = status or None
    if status and status not in {"Draft", "Active", "On Hold", "Closed"}:
        raise WorkflowError("Invalid JD status filter.")
    recruiter_id = optional_uuid(recruiter_id)
    rows = jobs(request, session).list_jobs(
        q=q, status=status, recruiter_id=recruiter_id, domain=domain, skill=skill
    )
    name = "job_rows" if request.headers.get("hx-request") == "true" else "directory"
    return render(
        request,
        session,
        name,
        rows=rows,
        filters=dict(q=q, status=status, recruiter_id=recruiter_id, domain=domain, skill=skill),
    )


@router.get("/requirements/new", include_in_schema=False)
def new_requirement(request: Request, session: Database):
    return render(request, session, "new", companies=company_directory(session))


@router.get("/requirements/{job_id}", include_in_schema=False)
def workspace(job_id: UUID, request: Request, session: Database):
    tz = request.app.state.settings.office_timezone
    job = jobs(request, session).get_job_detail(job_id)
    return render(
        request,
        session,
        "workspace",
        focus_stages=FOCUS_STAGES,
        focus_labels=FOCUS_LABELS,
        job=job,
        job_data=job.model_dump(mode="json"),
        companies=company_directory(session),
        history=ActivityService(session).get_job_history(job_id),
        tasks=TaskService(session, tz).list_my_tasks(job_id=job_id),
    )

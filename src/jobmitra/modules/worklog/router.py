from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from jobmitra.core.pages import render
from jobmitra.core.workflow import Database, WorkflowError, optional_uuid, same_origin
from jobmitra.modules.worklog.schemas import NoteCreate, TaskCreate, TaskPatch, TaskRead
from jobmitra.modules.worklog.service import ActivityService, TaskService

router = APIRouter(tags=["History and tasks"])


def tasks(request, session):
    return TaskService(session, request.app.state.settings.office_timezone)


@router.get("/api/jobs/{job_id}/activities")
def history(job_id: UUID, session: Database):
    return ActivityService(session).get_job_history(job_id)


@router.post("/api/jobs/{job_id}/notes", status_code=201, dependencies=[Depends(same_origin)])
def note(job_id: UUID, data: NoteCreate, session: Database):
    return ActivityService(session).add_note(job_id, data)


@router.get("/api/jobs/{job_id}/tasks", response_model=list[TaskRead])
def job_tasks(job_id: UUID, request: Request, session: Database):
    return tasks(request, session).list_my_tasks(job_id=job_id)


@router.post(
    "/api/jobs/{job_id}/tasks",
    response_model=TaskRead,
    status_code=201,
    dependencies=[Depends(same_origin)],
)
def create_task(job_id: UUID, data: TaskCreate, request: Request, session: Database):
    return tasks(request, session).create_task(job_id, data)


@router.get("/api/tasks", response_model=list[TaskRead])
def task_list(
    request: Request,
    session: Database,
    staff_id: UUID | None = None,
    status: Literal["Pending", "Done", "Cancelled"] | None = None,
):
    return tasks(request, session).list_my_tasks(staff_id=staff_id, status=status)


@router.patch("/api/tasks/{task_id}", response_model=TaskRead, dependencies=[Depends(same_origin)])
def edit_task(task_id: UUID, data: TaskPatch, request: Request, session: Database):
    return tasks(request, session).patch_task(task_id, data)


@router.get("/tasks", include_in_schema=False)
def task_page(
    request: Request,
    session: Database,
    staff_id: str | None = None,
    status: str | None = None,
):
    staff_id = optional_uuid(staff_id)
    status = status or None
    if status and status not in {"Pending", "Done", "Cancelled"}:
        raise WorkflowError("Invalid task status filter.")
    name = "task_rows" if request.headers.get("hx-request") == "true" else "tasks"
    return render(
        request,
        session,
        name,
        tasks=tasks(request, session).list_my_tasks(staff_id=staff_id, status=status),
        selected_staff=staff_id,
        selected_status=status,
    )

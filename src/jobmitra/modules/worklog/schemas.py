from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from jobmitra.core.validation import ReadModel
from jobmitra.modules.jobs.schemas import RecordedAction


class NoteCreate(RecordedAction):
    note: str = Field(min_length=1)


class TaskCreate(RecordedAction):
    title: str = Field(min_length=1, max_length=300)
    note: str | None = None
    assigned_staff_id: UUID
    due_date: date | None = None


class TaskPatch(RecordedAction):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    note: str | None = None
    assigned_staff_id: UUID | None = None
    due_date: date | None = None
    status: Literal["Done", "Cancelled"] | None = None


class TaskRead(ReadModel):
    id: UUID
    job_id: UUID
    title: str
    note: str | None
    assigned_staff_id: UUID
    assigned_staff_name: str
    created_by_staff_id: UUID
    due_date: date | None
    status: str
    completed_at: datetime | None
    completed_by_staff_id: UUID | None
    created_at: datetime
    updated_at: datetime
    job_title: str
    job_version: int
    is_overdue: bool

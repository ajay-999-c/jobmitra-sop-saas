from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from jobmitra.core.database import Base


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint("length(btrim(event_type))>0", name="ck_activity_type"),
        Index("ix_activity_job_timeline", "job_id", "occurred_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("job_requirements.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    actor_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("length(btrim(title))>0", name="ck_task_title"),
        CheckConstraint("status IN ('Pending','Done','Cancelled')", name="ck_task_status"),
        CheckConstraint(
            "(status='Done' AND completed_at IS NOT NULL AND completed_by_staff_id IS NOT"
            " NULL) OR (status<>'Done' AND completed_at IS NULL AND completed_by_staff_id"
            " IS NULL)",
            name="ck_task_completion",
        ),
        Index("ix_task_assignee_due", "assigned_staff_id", "status", "due_date"),
        Index("ix_task_job", "job_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("job_requirements.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    assigned_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    created_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="Pending", server_default="Pending")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

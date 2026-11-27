"""V12 employee operations over the existing UUID staff master, not a login system."""

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import DateTime, ForeignKey, Text, Uuid, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, undefer

from jobmitra.core.database import Base
from jobmitra.core.validation import InputModel
from jobmitra.core.workflow import same_origin
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.router import AtsRoute
from jobmitra.modules.ats_v2.unified_access import access
from jobmitra.modules.staff.models import StaffMember


class StaffChangeEvent(Base):
    __tablename__ = "staff_change_events"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    staff_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    request_hash: Mapped[str] = mapped_column(Text)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    actor_role: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmployeeInput(InputModel):
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    mobile: str | None = Field(default=None, max_length=50)
    designation: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    expected_revision: str | None = None

    @field_validator("email", "mobile", "designation", mode="before")
    @classmethod
    def optional_text(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid employee email address.")
        return value


def record(member):
    data = {
        k: getattr(member, k)
        for k in ("display_name", "email", "mobile", "designation", "is_active")
    }
    data["id"] = str(member.id)
    updated = member.updated_at
    data["updated_at"] = (
        updated.replace(tzinfo=UTC) if updated.tzinfo is None else updated.astimezone(UTC)
    ).isoformat()
    data["revision"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return data


def session_for(request):
    # Only tests/isolated deployments use another schema; public remains canonical.
    schema = getattr(request.app.state, "staff_schema", "public")
    engine = request.app.state.engine
    ats = getattr(request.app.state, "ats_v2_engine", None)
    if ats is not None:
        from jobmitra.modules.ats_v2 import workspace_store

        with ats.connect() as conn:
            workspace_store.require(conn)
        if ats.dialect.name == "sqlite":
            engine = ats
    if engine.dialect.name == "postgresql":
        engine = engine.execution_options(schema_translate_map={None: schema})
    return Session(engine)


def save(session, data, role, request_id, staff_id=None):
    fingerprint = hashlib.sha256(
        json.dumps([str(staff_id), data.model_dump()], sort_keys=True).encode()
    ).hexdigest()
    with session.begin():
        if session.bind.dialect.name == "postgresql":
            # Same canonical lock for staff creation/deactivation/reassignment trigger checks.
            from sqlalchemy import text

            session.execute(text("SELECT pg_advisory_xact_lock(12012, 11)"))
        prior = session.get(StaffChangeEvent, request_id)
        if prior:
            if prior.request_hash != fingerprint:
                raise AtsError("This request reference belongs to another employee change.", 409)
            return json.loads(prior.after_json)
        member = (
            session.scalar(
                select(StaffMember)
                .options(undefer("*"))
                .where(StaffMember.id == staff_id)
                .with_for_update()
            )
            if staff_id
            else None
        )
        if staff_id and member is None:
            raise AtsError("Employee not found.", 404)
        before = record(member) if member else None
        if member and data.expected_revision != before["revision"]:
            raise AtsError("Employee changed. Reload and review before saving.", 409)
        if member is None:
            member = StaffMember(id=uuid4())
            session.add(member)
        for key, value in data.model_dump(exclude={"expected_revision"}).items():
            setattr(member, key, value)
        member.updated_at = datetime.now(UTC)
        session.flush()
        after = record(member)
        session.add(
            StaffChangeEvent(
                id=request_id,
                staff_id=member.id,
                request_hash=fingerprint,
                before_json=json.dumps(before) if before else None,
                after_json=json.dumps(after),
                actor_role=role,
            )
        )
        return after


router = APIRouter(prefix="/api/v12/employees", route_class=AtsRoute, tags=["Employees"])


@router.get("")
def directory(
    request: Request,
    q: str = Query(default="", max_length=200),
    active_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    with session_for(request) as session:
        query = select(StaffMember).options(undefer("*"))
        if q:
            literal = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(StaffMember.display_name.ilike("%" + literal + "%", escape="\\"))
        if active_only:
            query = query.where(StaffMember.is_active.is_(True))
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        members = session.scalars(
            query.order_by(func.lower(StaffMember.display_name), StaffMember.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return {
            "items": [record(m) for m in members],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.post("", status_code=201, dependencies=[Depends(same_origin)])
def create(data: EmployeeInput, request: Request):
    role = access(request)
    try:
        key = UUID(request.headers.get("Idempotency-Key", ""))
    except ValueError:
        raise AtsError("A UUID request reference is required.") from None
    with session_for(request) as session:
        return save(session, data, role, key)


@router.patch("/{staff_id}", dependencies=[Depends(same_origin)])
def edit(staff_id: UUID, data: EmployeeInput, request: Request):
    role = access(request)
    try:
        key = UUID(request.headers.get("Idempotency-Key", ""))
    except ValueError:
        raise AtsError("A UUID request reference is required.") from None
    with session_for(request) as session:
        return save(session, data, role, key, staff_id)

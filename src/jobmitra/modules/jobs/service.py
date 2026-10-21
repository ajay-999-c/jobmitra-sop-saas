"""One transaction per employee action, including its parent version and audit event."""

from datetime import UTC, datetime

from pydantic import ValidationError

from jobmitra.core.workflow import WorkflowError, office_today
from jobmitra.modules.jobs import repository
from jobmitra.modules.jobs.models import JobRecruiter, JobRequirement
from jobmitra.modules.jobs.schemas import JobRead, ManualCriteria, StatusPatch
from jobmitra.modules.staff.models import StaffMember
from jobmitra.modules.staff.service import require_active
from jobmitra.modules.worklog.service import ActivityService


def target_state(job, today):
    value = (
        (lambda name: job.get(name)) if isinstance(job, dict) else (lambda name: getattr(job, name))
    )
    if value("target_date") is None:
        return "No Target"
    if value("target_milestone") == "SHORTLIST" and value("target_completed_at") is not None:
        return "Completed"
    days = (value("target_date") - today).days
    return (
        "Overdue"
        if days < 0
        else "Due Today"
        if days == 0
        else "Due Soon"
        if days <= 3
        else "Upcoming"
    )


def locked_job(session, job_id, version):
    job = repository.find(session, job_id, lock=True)
    if job is None:
        raise WorkflowError("JD not found.", 404)
    if job.version != version:
        raise WorkflowError("Someone changed this JD. Reload it before saving your changes.", 409)
    return job


def changes_for(job, values):
    changes = {}
    for key, value in values.items():
        old = getattr(job, key)
        if old != value:
            changes[key] = {"before": old, "after": value}
            setattr(job, key, value)
    return changes


def record_action(session, job, actor, event_type, changes, note=None):
    if changes or note:
        job.version += 1
        job.updated_at = datetime.now(UTC)
        ActivityService.append_change_event(session, job.id, actor, event_type, changes, note)
        session.flush()


def validate_company(session, values):
    if repository.company(session, values.company_id) is None:
        raise WorkflowError("Select an existing company.")
    if values.company_contact_id:
        contact = repository.contact(session, values.company_contact_id)
        if contact is None or contact.company_id != values.company_id:
            raise WorkflowError("The selected contact must belong to this company.")


class JobRequirementService:
    def __init__(self, session, timezone="Asia/Kolkata"):
        self.session, self.timezone = session, timezone

    def _read(self, job):
        values = {column.name: getattr(job, column.name) for column in job.__table__.columns}
        values.update(
            company_name=repository.company(self.session, job.company_id).company_name,
            recruiters=repository.active_recruiters(self.session, [job.id]).get(job.id, []),
            target_state=target_state(job, office_today(self.timezone)),
            target_verification="Tracking only; Selection/Joining need verified Stage 4 evidence."
            if job.target_milestone in {"SELECTION", "JOINING"}
            else "Staff-confirmed, self-selected attribution."
            if job.target_completed_at
            else None,
        )
        return JobRead.model_validate(values)

    def get_job_detail(self, job_id):
        job = repository.find(self.session, job_id)
        if job is None:
            raise WorkflowError("JD not found.", 404)
        return self._read(job)

    def list_jobs(self, **filters):
        rows = repository.directory(self.session, **filters)
        for row in rows:
            row["target_state"] = target_state(row, office_today(self.timezone))
        return rows

    def create_job(self, data):
        with self.session.begin():
            actor = require_active(self.session, [data.actor_staff_id])[data.actor_staff_id]
            validate_company(self.session, data)
            values = data.model_dump(exclude={"actor_staff_id", "closure_reason"})
            job = JobRequirement(**values, created_by_staff_id=actor.id)
            if data.status == "Closed":
                job.closed_at, job.closed_by_staff_id = datetime.now(UTC), actor.id
                job.closure_reason = data.closure_reason.strip()
            self.session.add(job)
            self.session.flush()
            ActivityService.append_change_event(
                self.session,
                job.id,
                actor,
                "JD_CREATED",
                {"created": {"before": None, "after": values}},
            )
            self.session.flush()
            return self._read(job)

    def update_manual_criteria(self, job_id, data):
        with self.session.begin():
            job = locked_job(self.session, job_id, data.version)
            actor = require_active(self.session, [data.actor_staff_id])[data.actor_staff_id]
            requested = data.model_fields_set - {"actor_staff_id", "version"}
            merged = {key: getattr(job, key) for key in ManualCriteria.model_fields}
            merged.update({key: getattr(data, key) for key in requested})
            try:
                validated = ManualCriteria.model_validate(merged)
            except ValidationError:
                raise WorkflowError(
                    "Invalid JD criteria: check required fields, ranges and missing values."
                ) from None
            validate_company(self.session, validated)
            changes = changes_for(job, {key: getattr(validated, key) for key in requested})
            if changes and job.ats_json is not None:
                changes.update(changes_for(job, {"ats_status": "Stale"}))
            record_action(self.session, job, actor, "JD_CRITERIA_CHANGED", changes)
            return self._read(job)

    def set_recruiters(self, job_id, data):
        with self.session.begin():
            job = locked_job(self.session, job_id, data.version)
            rows = {row.staff_id: row for row in repository.recruiter_rows(self.session, job.id)}
            before = {key for key, row in rows.items() if row.removed_at is None}
            after = set(data.staff_ids)
            actor = require_active(self.session, (after - before) | {data.actor_staff_id})[
                data.actor_staff_id
            ]
            if before != after:
                now = datetime.now(UTC)
                for staff_id in before - after:
                    rows[staff_id].removed_at = max(now, rows[staff_id].assigned_at)
                for staff_id in after - before:
                    if staff_id in rows:
                        rows[staff_id].removed_at, rows[staff_id].assigned_at = None, now
                    else:
                        self.session.add(
                            JobRecruiter(job_id=job.id, staff_id=staff_id, assigned_at=now)
                        )

                def names(ids):
                    return [
                        {
                            "staff_id": str(key),
                            "display_name": self.session.get(StaffMember, key).display_name,
                        }
                        for key in sorted(ids)
                    ]

                record_action(
                    self.session,
                    job,
                    actor,
                    "RECRUITERS_CHANGED",
                    {"recruiters": {"before": names(before), "after": names(after)}},
                )
            return self._read(job)

    def change_work_focus(self, job_id, data):
        with self.session.begin():
            job = locked_job(self.session, job_id, data.version)
            actor = require_active(self.session, [data.actor_staff_id])[data.actor_staff_id]
            record_action(
                self.session,
                job,
                actor,
                "WORK_FOCUS_CHANGED",
                changes_for(job, {"current_work_focus": data.current_work_focus}),
            )
            return self._read(job)

    def change_target(self, job_id, data):
        with self.session.begin():
            job = locked_job(self.session, job_id, data.version)
            actor = require_active(self.session, [data.actor_staff_id])[data.actor_staff_id]
            changes = changes_for(
                job, {"target_date": data.target_date, "target_milestone": data.target_milestone}
            )
            if changes:
                changes.update(
                    changes_for(
                        job, {"target_completed_at": None, "target_completed_by_staff_id": None}
                    )
                )
            record_action(self.session, job, actor, "TARGET_CHANGED", changes)
            return self._read(job)

    def confirm_shortlist(self, job_id, data):
        with self.session.begin():
            job = locked_job(self.session, job_id, data.version)
            actor = require_active(self.session, [data.actor_staff_id])[data.actor_staff_id]
            if job.target_milestone != "SHORTLIST" or job.target_date is None:
                raise WorkflowError(
                    "Only SHORTLIST can be staff-confirmed in Stage 2; "
                    "Selection/Joining require Stage 4 evidence."
                )
            changes = (
                {}
                if job.target_completed_at
                else changes_for(
                    job,
                    {
                        "target_completed_at": datetime.now(UTC),
                        "target_completed_by_staff_id": actor.id,
                    },
                )
            )
            record_action(self.session, job, actor, "SHORTLIST_STAFF_CONFIRMED", changes)
            return self._read(job)

    def change_status(self, job_id, data):
        with self.session.begin():
            job = locked_job(self.session, job_id, data.version)
            actor = require_active(self.session, [data.actor_staff_id])[data.actor_staff_id]
            values = {"status": data.status}
            if data.status == "Closed":
                values.update(
                    closure_reason=data.closure_reason.strip(),
                    closed_at=job.closed_at or datetime.now(UTC),
                    closed_by_staff_id=job.closed_by_staff_id or actor.id,
                )
            else:
                values.update(closure_reason=None, closed_at=None, closed_by_staff_id=None)
            record_action(self.session, job, actor, "STATUS_CHANGED", changes_for(job, values))
            return self._read(job)

    def close_job(self, job_id, *, actor_staff_id, version, closure_reason):
        return self.change_status(
            job_id,
            StatusPatch(
                actor_staff_id=actor_staff_id,
                version=version,
                status="Closed",
                closure_reason=closure_reason,
            ),
        )

    def save_ats_json(self, job_id, data):
        with self.session.begin():
            job = locked_job(self.session, job_id, data.version)
            actor = require_active(self.session, [data.actor_staff_id])[data.actor_staff_id]
            values = {
                "ats_json": data.ats.model_dump(mode="json"),
                "ats_schema_version": 1,
                "ats_status": "Reviewed" if data.reviewed else "Draft",
            }
            record_action(
                self.session, job, actor, "ATS_ENRICHMENT_CHANGED", changes_for(job, values)
            )
            return self._read(job)

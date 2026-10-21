from datetime import UTC, datetime

from jobmitra.core.workflow import WorkflowError, json_value, office_today
from jobmitra.modules.staff.service import require_active
from jobmitra.modules.worklog import repository
from jobmitra.modules.worklog.models import Activity, Task
from jobmitra.modules.worklog.schemas import TaskPatch, TaskRead


class ActivityService:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def append_change_event(session, job_id, actor, event_type, changes, note=None):
        session.add(
            Activity(
                job_id=job_id,
                actor_staff_id=actor.id,
                event_type=event_type,
                note=note,
                changes={
                    "fields": json_value(changes),
                    "actor": {
                        "id": str(actor.id),
                        "display_name": actor.display_name,
                        "attribution": "self-selected/unverified",
                    },
                },
            )
        )

    def add_note(self, job_id, data):
        from jobmitra.modules.jobs.service import locked_job, record_action

        with self.session.begin():
            job = locked_job(self.session, job_id, data.version)
            actor = require_active(self.session, [data.actor_staff_id])[data.actor_staff_id]
            record_action(self.session, job, actor, "NOTE_ADDED", {}, data.note)
            return {"job_id": job.id, "version": job.version}

    def get_job_history(self, job_id):
        from jobmitra.modules.jobs.repository import find

        if find(self.session, job_id) is None:
            raise WorkflowError("JD not found.", 404)
        result = []
        for event, current_name in repository.history(self.session, job_id):
            values = {
                column.name: getattr(event, column.name) for column in event.__table__.columns
            }
            values["actor_display_name"] = (
                (event.changes or {}).get("actor", {}).get("display_name", current_name)
            )
            result.append(values)
        return result


class TaskService:
    def __init__(self, session, timezone="Asia/Kolkata"):
        self.session, self.timezone = session, timezone

    def list_my_tasks(self, *, staff_id=None, status=None, job_id=None, task_id=None):
        result = []
        for task, staff_name, job_title, version in self.session.execute(
            repository.tasks(
                self.session, staff_id=staff_id, status=status, job_id=job_id, task_id=task_id
            )
        ):
            values = {column.name: getattr(task, column.name) for column in task.__table__.columns}
            values.update(
                assigned_staff_name=staff_name,
                job_title=job_title,
                job_version=version,
                is_overdue=task.status == "Pending"
                and task.due_date is not None
                and task.due_date < office_today(self.timezone),
            )
            result.append(TaskRead.model_validate(values))
        return result

    def create_task(self, job_id, data):
        from jobmitra.modules.jobs.service import locked_job, record_action

        with self.session.begin():
            job = locked_job(self.session, job_id, data.version)
            members = require_active(self.session, [data.actor_staff_id, data.assigned_staff_id])
            task = Task(
                job_id=job.id,
                title=data.title,
                note=data.note,
                assigned_staff_id=data.assigned_staff_id,
                created_by_staff_id=data.actor_staff_id,
                due_date=data.due_date,
            )
            self.session.add(task)
            self.session.flush()
            record_action(
                self.session,
                job,
                members[data.actor_staff_id],
                "TASK_CREATED",
                {
                    "task": {
                        "before": None,
                        "after": {
                            "id": task.id,
                            "title": task.title,
                            "note": task.note,
                            "assigned_staff_id": task.assigned_staff_id,
                            "due_date": task.due_date,
                            "status": task.status,
                        },
                    }
                },
            )
            return self.list_my_tasks(task_id=task.id)[0]

    def patch_task(self, task_id, data):
        from jobmitra.modules.jobs.service import changes_for, locked_job, record_action

        with self.session.begin():
            task = repository.task(self.session, task_id)
            if task is None:
                raise WorkflowError("Task not found.", 404)
            job = locked_job(self.session, task.job_id, data.version)
            task = repository.task(self.session, task_id, refresh=True)
            fields = data.model_fields_set - {"actor_staff_id", "version"}
            if any(
                getattr(data, key) is None
                for key in fields & {"title", "assigned_staff_id", "status"}
            ):
                raise WorkflowError("Task title, assignee and status cannot be cleared.")
            new_members = {data.actor_staff_id}
            if "assigned_staff_id" in fields and data.assigned_staff_id != task.assigned_staff_id:
                if task.status != "Pending":
                    raise WorkflowError("Only pending tasks can be reassigned.")
                new_members.add(data.assigned_staff_id)
            actor = require_active(self.session, new_members)[data.actor_staff_id]
            values = {key: getattr(data, key) for key in fields}
            if "status" in fields and data.status != task.status:
                if task.status != "Pending":
                    raise WorkflowError("Only pending tasks can be completed or cancelled.")
                values.update(
                    completed_at=datetime.now(UTC) if data.status == "Done" else None,
                    completed_by_staff_id=actor.id if data.status == "Done" else None,
                )
            changes = changes_for(task, values)
            record_action(
                self.session,
                job,
                actor,
                "TASK_CHANGED",
                {"task_id": str(task.id), "task_fields": changes} if changes else {},
            )
            return self.list_my_tasks(task_id=task.id)[0]

    def mark_done(self, task_id, *, actor_staff_id, version):
        return self.patch_task(
            task_id, TaskPatch(actor_staff_id=actor_staff_id, version=version, status="Done")
        )

    def cancel_task(self, task_id, *, actor_staff_id, version):
        return self.patch_task(
            task_id, TaskPatch(actor_staff_id=actor_staff_id, version=version, status="Cancelled")
        )

    def reassign_task(self, task_id, *, actor_staff_id, version, assigned_staff_id):
        return self.patch_task(
            task_id,
            TaskPatch(
                actor_staff_id=actor_staff_id, version=version, assigned_staff_id=assigned_staff_id
            ),
        )

from sqlalchemy import select

from jobmitra.modules.jobs.models import JobRequirement
from jobmitra.modules.staff.models import StaffMember
from jobmitra.modules.worklog.models import Activity, Task


def history(session, job_id):
    return session.execute(
        select(Activity, StaffMember.display_name)
        .outerjoin(StaffMember, Activity.actor_staff_id == StaffMember.id)
        .where(Activity.job_id == job_id)
        .order_by(Activity.occurred_at.desc(), Activity.id.desc())
    ).all()


def task(session, task_id, *, refresh=False):
    query = select(Task).where(Task.id == task_id)
    if refresh:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalar(query)


def tasks(session, *, staff_id=None, status=None, job_id=None, task_id=None):
    query = (
        select(Task, StaffMember.display_name, JobRequirement.job_title, JobRequirement.version)
        .join(StaffMember, StaffMember.id == Task.assigned_staff_id)
        .join(JobRequirement, JobRequirement.id == Task.job_id)
    )
    if staff_id:
        query = query.where(Task.assigned_staff_id == staff_id)
    if status:
        query = query.where(Task.status == status)
    if job_id:
        query = query.where(Task.job_id == job_id)
    if task_id:
        query = query.where(Task.id == task_id)
    return query.order_by(Task.due_date.asc().nulls_last(), Task.created_at, Task.id)

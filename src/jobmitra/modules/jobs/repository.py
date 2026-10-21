from sqlalchemy import func, or_, select

from jobmitra.modules.companies.models import Company, CompanyContact
from jobmitra.modules.jobs.models import JobRecruiter, JobRequirement
from jobmitra.modules.staff.models import StaffMember


def find(session, job_id, *, lock=False):
    query = select(JobRequirement).where(JobRequirement.id == job_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalar(query)


def company(session, company_id):
    return session.get(Company, company_id)


def contact(session, contact_id):
    return session.get(CompanyContact, contact_id)


def recruiter_rows(session, job_id):
    return list(session.scalars(select(JobRecruiter).where(JobRecruiter.job_id == job_id)))


def active_recruiters(session, job_ids):
    result = {}
    if not job_ids:
        return result
    rows = session.execute(
        select(JobRecruiter.job_id, StaffMember.id, StaffMember.display_name, StaffMember.is_active)
        .join(StaffMember, StaffMember.id == JobRecruiter.staff_id)
        .where(JobRecruiter.job_id.in_(job_ids), JobRecruiter.removed_at.is_(None))
        .order_by(StaffMember.display_name, StaffMember.id)
    )
    for row in rows:
        result.setdefault(row.job_id, []).append(
            {"id": str(row.id), "display_name": row.display_name, "is_active": row.is_active}
        )
    return result


def directory(
    session,
    *,
    q=None,
    status=None,
    recruiter_id=None,
    domain=None,
    skill=None,
    through=None,
    company_id=None,
):
    columns = (
        "id",
        "company_id",
        "job_title",
        "status",
        "domain_key",
        "location_text",
        "required_skills",
        "target_date",
        "target_milestone",
        "target_completed_at",
        "version",
        "updated_at",
    )
    query = select(*(getattr(JobRequirement, key) for key in columns), Company.company_name).join(
        Company, Company.id == JobRequirement.company_id
    )
    if company_id:
        query = query.where(JobRequirement.company_id == company_id)
    if q:
        query = query.where(
            or_(Company.company_name.ilike(f"%{q}%"), JobRequirement.job_title.ilike(f"%{q}%"))
        )
    if status:
        query = query.where(JobRequirement.status == status)
    if recruiter_id:
        query = query.where(
            select(JobRecruiter.job_id)
            .where(
                JobRecruiter.job_id == JobRequirement.id,
                JobRecruiter.staff_id == recruiter_id,
                JobRecruiter.removed_at.is_(None),
            )
            .exists()
        )
    if domain:
        query = query.where(JobRequirement.domain_key.ilike(f"%{domain}%"))
    if skill:
        query = query.where(
            or_(
                func.array_to_string(JobRequirement.required_skills, " ").ilike(f"%{skill}%"),
                func.array_to_string(JobRequirement.preferred_skills, " ").ilike(f"%{skill}%"),
            )
        )
    if through:
        query = query.where(
            JobRequirement.target_date <= through,
            JobRequirement.target_completed_at.is_(None),
            JobRequirement.status != "Closed",
        )
    rows = [
        dict(row)
        for row in session.execute(
            query.order_by(
                JobRequirement.target_date.asc().nulls_last(),
                JobRequirement.job_title,
                JobRequirement.id,
            )
        ).mappings()
    ]
    recruiters = active_recruiters(session, [row["id"] for row in rows])
    for row in rows:
        row["recruiters"] = recruiters.get(row["id"], [])
    return rows


def status_counts(session):
    return dict(
        session.execute(
            select(JobRequirement.status, func.count()).group_by(JobRequirement.status)
        ).all()
    )

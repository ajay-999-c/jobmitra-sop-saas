from sqlalchemy import select

from jobmitra.modules.staff.models import StaffMember


def list_staff(session, *, active_only=False):
    query = select(StaffMember).order_by(StaffMember.display_name, StaffMember.id)
    if active_only:
        query = query.where(StaffMember.is_active.is_(True))
    return list(session.scalars(query))


def find(session, staff_id, *, lock=False):
    query = select(StaffMember).where(StaffMember.id == staff_id)
    return session.scalar(query.with_for_update() if lock else query)


def lock_members(session, ids):
    return list(
        session.scalars(
            select(StaffMember)
            .where(StaffMember.id.in_(ids))
            .order_by(StaffMember.id)
            .with_for_update()
        )
    )

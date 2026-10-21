from jobmitra.core.workflow import WorkflowError
from jobmitra.modules.staff import repository
from jobmitra.modules.staff.models import StaffMember
from jobmitra.modules.staff.schemas import StaffPatch, StaffRead


def require_active(session, ids):
    """Validate and lock all new participants together, in stable ID order."""
    ids = set(ids)
    members = {row.id: row for row in repository.lock_members(session, ids)}
    if members.keys() != ids or any(not row.is_active for row in members.values()):
        raise WorkflowError("Select existing active staff for recording and new assignments.")
    return members


def staff_read(session, member):
    key = " ".join(member.display_name.split()).casefold()
    duplicate = any(
        row.id != member.id and " ".join(row.display_name.split()).casefold() == key
        for row in repository.list_staff(session)
    )
    return StaffRead.model_validate(member).model_copy(update={"duplicate_name_warning": duplicate})


class StaffService:
    def __init__(self, session):
        self.session = session

    def add_staff(self, data):
        with self.session.begin():
            member = StaffMember(display_name=data.display_name)
            self.session.add(member)
            self.session.flush()
            return staff_read(self.session, member)

    def patch_staff(self, staff_id, data):
        with self.session.begin():
            member = repository.find(self.session, staff_id, lock=True)
            if member is None:
                raise WorkflowError("Staff member not found.", 404)
            if any(getattr(data, key) is None for key in data.model_fields_set):
                raise WorkflowError("Staff name and active flag cannot be cleared.")
            for key in data.model_fields_set:
                setattr(member, key, getattr(data, key))
            self.session.flush()
            return staff_read(self.session, member)

    def rename_staff(self, staff_id, display_name):
        return self.patch_staff(staff_id, StaffPatch(display_name=display_name))

    def deactivate_staff(self, staff_id):
        return self.patch_staff(staff_id, StaffPatch(is_active=False))

    def list_active_staff(self):
        return repository.list_staff(self.session, active_only=True)

"""Explicit model registration for composition and additive migration comparisons."""

from jobmitra.modules.jobs.models import JobRecruiter, JobRequirement
from jobmitra.modules.staff.models import StaffMember
from jobmitra.modules.worklog.models import Activity, Task

STAGE2_MODELS = (StaffMember, JobRequirement, JobRecruiter, Activity, Task)
STAGE2_TABLES = frozenset(model.__tablename__ for model in STAGE2_MODELS)

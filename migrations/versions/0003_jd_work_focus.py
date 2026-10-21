"""Add nullable manual JD work focus; no backfill or candidate progression.

Revision ID: 0003_jd_work_focus
Revises: 0002_jd_tracking
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_jd_work_focus"
down_revision = "0002_jd_tracking"
branch_labels = None
depends_on = None

# Keep applied migration definitions independent of future application constants.
ALLOWED = (
    "current_work_focus IN ('CANDIDATE_POOL','CANDIDATE_CONTACT',"
    "'JOBMITRA_SCREENING','COMPANY_SUBMISSION','INTERVIEWS','SELECTION','JOINING')"
)


def upgrade():
    op.add_column("job_requirements", sa.Column("current_work_focus", sa.Text(), nullable=True))
    op.create_check_constraint("ck_job_work_focus", "job_requirements", ALLOWED)


def downgrade():
    op.drop_constraint("ck_job_work_focus", "job_requirements", type_="check")
    op.drop_column("job_requirements", "current_work_focus")

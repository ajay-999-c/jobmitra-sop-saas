"""Store unclassified JD skills separately; preserve all historical criteria.

Revision ID: 0005_jd_general_skills
Revises: 0004_candidate_desk
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_jd_general_skills"
down_revision = "0004_candidate_desk"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "job_requirements",
        sa.Column(
            "general_skills",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.create_check_constraint(
        "ck_job_general_skills_no_nulls",
        "job_requirements",
        "array_position(general_skills,NULL) IS NULL",
    )


def downgrade():
    op.drop_constraint("ck_job_general_skills_no_nulls", "job_requirements", type_="check")
    op.drop_column("job_requirements", "general_skills")

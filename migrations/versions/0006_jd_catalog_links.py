"""Add optional shared catalog links to JDs; preserve legacy text, no backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0006_jd_catalog_links"
down_revision = "0005_jd_general_skills"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job_requirements", sa.Column("domain_id", sa.Uuid(), nullable=True))
    op.add_column("job_requirements", sa.Column("subdomain_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_job_domain",
        "job_requirements",
        "work_domains",
        ["domain_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_job_subdomain_parent",
        "job_requirements",
        "work_subdomains",
        ["subdomain_id", "domain_id"],
        ["id", "domain_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_job_subdomain_domain",
        "job_requirements",
        "subdomain_id IS NULL OR domain_id IS NOT NULL",
    )


def downgrade():
    op.drop_constraint("ck_job_subdomain_domain", "job_requirements", type_="check")
    op.drop_constraint("fk_job_subdomain_parent", "job_requirements", type_="foreignkey")
    op.drop_constraint("fk_job_domain", "job_requirements", type_="foreignkey")
    op.drop_column("job_requirements", "subdomain_id")
    op.drop_column("job_requirements", "domain_id")

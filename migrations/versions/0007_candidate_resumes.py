"""Optional original resumes; additive metadata only, no existing-data backfill."""

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "0007_candidate_resumes"
down_revision = "0006_jd_catalog_links"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "candidate_resumes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.Text(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("parsed_json", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("parsing_status", sa.Text(), server_default="not_parsed", nullable=False),
        sa.Column("parsing_error", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("storage_key", name="uq_candidate_resume_storage"),
        sa.CheckConstraint(
            "file_size > 0 AND file_hash ~ '^[0-9a-f]{64}$'", name="ck_candidate_resume_integrity"
        ),
        sa.CheckConstraint(
            "parsing_status IN ('not_parsed','processing','parsed','failed')",
            name="ck_candidate_resume_parsing",
        ),
    )
    op.create_index(
        "uq_candidate_resume_active",
        "candidate_resumes",
        ["candidate_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ix_candidate_resume_history", "candidate_resumes", ["candidate_id", "uploaded_at"]
    )


def downgrade():
    # Never discard metadata for preserved private originals, even on an explicit downgrade.
    if context.is_offline_mode():
        raise RuntimeError("Resume downgrade requires an online empty-table check")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM candidate_resumes)")):
        raise RuntimeError("Resume metadata exists; archive it before reviewing a downgrade")
    op.drop_table("candidate_resumes")

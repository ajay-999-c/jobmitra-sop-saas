"""Add paperless Candidate Desk

Revision ID: 0004_candidate_desk
Revises: 0003_jd_work_focus
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_candidate_desk"
down_revision: str | Sequence[str] | None = "0003_jd_work_focus"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_domains",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND length(normalized_name)>0 AND length(key)>0",
            name="ck_work_domain_name",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_work_domain_key"),
        sa.UniqueConstraint("normalized_name", name="uq_work_domain_name"),
    )
    op.create_table(
        "work_subdomains",
        sa.Column("domain_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(name))>0 AND length(normalized_name)>0 AND length(key)>0",
            name="ck_work_subdomain_name",
        ),
        sa.ForeignKeyConstraint(["domain_id"], ["work_domains.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain_id", "key", name="uq_work_subdomain_key"),
        sa.UniqueConstraint("domain_id", "normalized_name", name="uq_work_subdomain_name"),
        sa.UniqueConstraint("id", "domain_id", name="uq_work_subdomain_parent"),
    )
    op.create_table(
        "candidates",
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("mobile", sa.Text(), nullable=False),
        sa.Column("mobile_normalized", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("role_title", sa.Text(), nullable=True),
        sa.Column("domain_id", sa.Uuid(), nullable=True),
        sa.Column("subdomain_id", sa.Uuid(), nullable=True),
        sa.Column("qualification", sa.Text(), nullable=True),
        sa.Column("experience_months", sa.Integer(), nullable=True),
        sa.Column(
            "skills",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("current_location", sa.Text(), nullable=True),
        sa.Column(
            "preferred_locations",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("hometown", sa.Text(), nullable=True),
        sa.Column("home_state", sa.Text(), nullable=True),
        sa.Column("ready_to_relocate", sa.Boolean(), nullable=True),
        sa.Column("current_salary_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("current_salary_period", sa.Text(), server_default="Unknown", nullable=False),
        sa.Column("current_salary_basis", sa.Text(), server_default="Unknown", nullable=False),
        sa.Column("expected_salary_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("expected_salary_period", sa.Text(), server_default="Unknown", nullable=False),
        sa.Column("expected_salary_basis", sa.Text(), server_default="Unknown", nullable=False),
        sa.Column("last_salary_raw", sa.Text(), nullable=True),
        sa.Column("notice_period_text", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "current_salary_amount >= 0 AND current_salary_amount <> 'NaN'::numeric"
                " AND expected_salary_amount >= 0 AND expected_salary_amount <> 'NaN'::"
                "numeric"
            ),
            name="ck_candidate_salary",
        ),
        sa.CheckConstraint(
            (
                "current_salary_basis IN ('CTC','Gross','Take-home','Unknown') AND expe"
                "cted_salary_basis IN ('CTC','Gross','Take-home','Unknown')"
            ),
            name="ck_candidate_salary_basis",
        ),
        sa.CheckConstraint(
            (
                "current_salary_period IN ('Monthly','Annual','Unknown') AND expected_s"
                "alary_period IN ('Monthly','Annual','Unknown')"
            ),
            name="ck_candidate_salary_period",
        ),
        sa.CheckConstraint("mobile_normalized ~ '^[0-9]{8,15}$'", name="ck_candidate_mobile"),
        sa.CheckConstraint(
            "source IN ('Walk-in','Foundit','WhatsApp','Referral','Existing database','Other')",
            name="ck_candidate_source",
        ),
        sa.CheckConstraint(
            (
                "array_position(skills,NULL) IS NULL AND array_position(preferred_locat"
                "ions,NULL) IS NULL"
            ),
            name="ck_candidate_arrays",
        ),
        sa.CheckConstraint("experience_months >= 0", name="ck_candidate_experience"),
        sa.CheckConstraint("length(btrim(full_name))>0", name="ck_candidate_name"),
        sa.CheckConstraint(
            "subdomain_id IS NULL OR domain_id IS NOT NULL", name="ck_candidate_subdomain_domain"
        ),
        sa.CheckConstraint("version > 0", name="ck_candidate_version"),
        sa.ForeignKeyConstraint(["domain_id"], ["work_domains.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["subdomain_id", "domain_id"],
            ["work_subdomains.id", "work_subdomains.domain_id"],
            name="fk_candidate_subdomain_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_candidate_domain", "candidates", ["domain_id", "subdomain_id"], unique=False
    )
    op.create_index("ix_candidate_email", "candidates", ["email"], unique=False)
    op.create_index("ix_candidate_mobile", "candidates", ["mobile_normalized"], unique=False)
    op.create_index("ix_candidate_name", "candidates", ["full_name"], unique=False)
    op.create_table(
        "candidate_documents",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("uploaded_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("approval_status", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "(kind='MODIFIED_RESUME' AND source_document_id IS NOT NULL AND approva"
                "l_status='Reviewed') OR (kind<>'MODIFIED_RESUME' AND source_document_i"
                "d IS NULL)"
            ),
            name="ck_document_lineage",
        ),
        sa.CheckConstraint(
            (
                "content_type IN ('application/pdf','application/vnd.openxmlformats-off"
                "icedocument.wordprocessingml.document')"
            ),
            name="ck_document_content_type",
        ),
        sa.CheckConstraint(
            "kind IN ('ORIGINAL_RESUME','MODIFIED_RESUME','AUTHORITY')", name="ck_document_kind"
        ),
        sa.CheckConstraint(
            "size_bytes>0 AND version>0 AND sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_integrity"
        ),
        sa.CheckConstraint(
            "source_document_id IS NULL OR source_document_id<>id", name="ck_document_not_self"
        ),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_document_id", "candidate_id"],
            ["candidate_documents.id", "candidate_documents.candidate_id"],
            name="fk_document_source_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "kind", "version", name="uq_document_version"),
        sa.UniqueConstraint("id", "candidate_id", name="uq_document_candidate"),
        sa.UniqueConstraint("id", "kind", name="uq_document_kind"),
        sa.UniqueConstraint("storage_key", name="uq_document_storage"),
    )
    op.create_table(
        "candidate_visits",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("visited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("recorded_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("authority_status", sa.Text(), server_default="Not recorded", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "authority_status IN ('Not recorded','Pending','Signed (reported)','Not signed')",
            name="ck_candidate_visit_authority",
        ),
        sa.CheckConstraint("length(btrim(purpose))>0", name="ck_candidate_visit_purpose"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["recorded_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_visit_day", "candidate_visits", ["visited_at"], unique=False)
    op.create_index(
        "ix_candidate_visit_timeline",
        "candidate_visits",
        ["candidate_id", "visited_at"],
        unique=False,
    )
    op.create_table(
        "job_search_requests",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("desired_role", sa.Text(), nullable=False),
        sa.Column(
            "preferred_locations",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("assigned_staff_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default="Searching", nullable=False),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status IN ('Placed','Closed')) = (closed_at IS NOT NULL)", name="ck_search_closed"
        ),
        sa.CheckConstraint(
            "status IN ('Searching','Interviewing','On Hold','Placed','Closed')",
            name="ck_search_status",
        ),
        sa.CheckConstraint(
            "array_position(preferred_locations,NULL) IS NULL", name="ck_search_locations"
        ),
        sa.CheckConstraint(
            "length(btrim(desired_role))>0 AND version>0", name="ck_search_role_version"
        ),
        sa.ForeignKeyConstraint(["assigned_staff_id"], ["staff_members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_search_assignee_due",
        "job_search_requests",
        ["assigned_staff_id", "status", "follow_up_date"],
        unique=False,
    )
    op.create_index("ix_search_candidate", "job_search_requests", ["candidate_id"], unique=False)
    op.create_table(
        "resume_parse_results",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_kind", sa.Text(), server_default="ORIGINAL_RESUME", nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_label", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("parsed_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "validation_status", sa.Text(), server_default="Structurally checked", nullable=False
        ),
        sa.Column("review_status", sa.Text(), server_default="Unreviewed", nullable=False),
        sa.Column("pasted_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "(review_status='Unreviewed' AND reviewed_at IS NULL AND reviewed_by_st"
                "aff_id IS NULL) OR (review_status IN ('Reviewed','Rejected') AND revie"
                "wed_at IS NOT NULL AND reviewed_by_staff_id IS NOT NULL)"
            ),
            name="ck_parse_review",
        ),
        sa.CheckConstraint("document_kind='ORIGINAL_RESUME'", name="ck_parse_original"),
        sa.CheckConstraint("jsonb_typeof(parsed_json)='object'", name="ck_parse_object"),
        sa.CheckConstraint("provider IN ('ChatGPT','Claude')", name="ck_parse_provider"),
        sa.CheckConstraint("validation_status='Structurally checked'", name="ck_parse_validation"),
        sa.CheckConstraint("schema_version=1", name="ck_parse_schema"),
        sa.ForeignKeyConstraint(
            ["document_id", "document_kind"],
            ["candidate_documents.id", "candidate_documents.kind"],
            name="fk_parse_original_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["pasted_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reviewed_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_parse_document_time",
        "resume_parse_results",
        ["document_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_parse_document_time", table_name="resume_parse_results")
    op.drop_table("resume_parse_results")
    op.drop_index("ix_search_candidate", table_name="job_search_requests")
    op.drop_index("ix_search_assignee_due", table_name="job_search_requests")
    op.drop_table("job_search_requests")
    op.drop_index("ix_candidate_visit_timeline", table_name="candidate_visits")
    op.drop_index("ix_candidate_visit_day", table_name="candidate_visits")
    op.drop_table("candidate_visits")
    op.drop_table("candidate_documents")
    op.drop_index("ix_candidate_name", table_name="candidates")
    op.drop_index("ix_candidate_mobile", table_name="candidates")
    op.drop_index("ix_candidate_email", table_name="candidates")
    op.drop_index("ix_candidate_domain", table_name="candidates")
    op.drop_table("candidates")
    op.drop_table("work_subdomains")
    op.drop_table("work_domains")

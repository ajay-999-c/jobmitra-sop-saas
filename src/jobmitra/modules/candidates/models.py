"""Seven additive Candidate Desk tables. No cascading deletion of personal records."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from jobmitra.core.database import Base


class Identity:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Updated:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkDomain(Identity, Updated, Base):
    __tablename__ = "work_domains"
    __table_args__ = (
        UniqueConstraint("key", name="uq_work_domain_key"),
        UniqueConstraint("normalized_name", name="uq_work_domain_name"),
        CheckConstraint(
            "length(btrim(name)) > 0 AND length(normalized_name)>0 AND length(key)>0",
            name="ck_work_domain_name",
        ),
    )
    key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class WorkSubdomain(Identity, Updated, Base):
    __tablename__ = "work_subdomains"
    __table_args__ = (
        UniqueConstraint("domain_id", "normalized_name", name="uq_work_subdomain_name"),
        UniqueConstraint("domain_id", "key", name="uq_work_subdomain_key"),
        UniqueConstraint("id", "domain_id", name="uq_work_subdomain_parent"),
        CheckConstraint(
            "length(btrim(name))>0 AND length(normalized_name)>0 AND length(key)>0",
            name="ck_work_subdomain_name",
        ),
    )
    domain_id: Mapped[UUID] = mapped_column(ForeignKey("work_domains.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class Candidate(Identity, Updated, Base):
    __tablename__ = "candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["subdomain_id", "domain_id"],
            ["work_subdomains.id", "work_subdomains.domain_id"],
            name="fk_candidate_subdomain_parent",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "subdomain_id IS NULL OR domain_id IS NOT NULL", name="ck_candidate_subdomain_domain"
        ),
        CheckConstraint("length(btrim(full_name))>0", name="ck_candidate_name"),
        CheckConstraint("mobile_normalized ~ '^[0-9]{8,15}$'", name="ck_candidate_mobile"),
        CheckConstraint(
            "source IN ('Walk-in','Foundit','WhatsApp','Referral','Existing database','Other')",
            name="ck_candidate_source",
        ),
        CheckConstraint("experience_months >= 0", name="ck_candidate_experience"),
        CheckConstraint("version > 0", name="ck_candidate_version"),
        CheckConstraint(
            (
                "current_salary_amount >= 0 AND current_salary_amount <> 'NaN'::numeric AN"
                "D expected_salary_amount >= 0 AND expected_salary_amount <> 'NaN'::numeri"
                "c"
            ),
            name="ck_candidate_salary",
        ),
        CheckConstraint(
            (
                "current_salary_period IN ('Monthly','Annual','Unknown') AND expected_sala"
                "ry_period IN ('Monthly','Annual','Unknown')"
            ),
            name="ck_candidate_salary_period",
        ),
        CheckConstraint(
            (
                "current_salary_basis IN ('CTC','Gross','Take-home','Unknown') AND expecte"
                "d_salary_basis IN ('CTC','Gross','Take-home','Unknown')"
            ),
            name="ck_candidate_salary_basis",
        ),
        CheckConstraint(
            (
                "array_position(skills,NULL) IS NULL AND array_position(preferred_location"
                "s,NULL) IS NULL"
            ),
            name="ck_candidate_arrays",
        ),
        Index("ix_candidate_mobile", "mobile_normalized"),
        Index("ix_candidate_name", "full_name"),
        Index("ix_candidate_email", "email"),
        Index("ix_candidate_domain", "domain_id", "subdomain_id"),
    )
    full_name: Mapped[str] = mapped_column(Text)
    mobile: Mapped[str] = mapped_column(Text)
    mobile_normalized: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    role_title: Mapped[str | None] = mapped_column(Text)
    domain_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("work_domains.id", ondelete="RESTRICT")
    )
    subdomain_id: Mapped[UUID | None] = mapped_column(Uuid)
    qualification: Mapped[str | None] = mapped_column(Text)
    experience_months: Mapped[int | None] = mapped_column(Integer)
    skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    current_location: Mapped[str | None] = mapped_column(Text)
    preferred_locations: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    hometown: Mapped[str | None] = mapped_column(Text)
    home_state: Mapped[str | None] = mapped_column(Text)
    ready_to_relocate: Mapped[bool | None] = mapped_column(Boolean)
    current_salary_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    current_salary_period: Mapped[str] = mapped_column(
        Text, default="Unknown", server_default="Unknown"
    )
    current_salary_basis: Mapped[str] = mapped_column(
        Text, default="Unknown", server_default="Unknown"
    )
    expected_salary_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    expected_salary_period: Mapped[str] = mapped_column(
        Text, default="Unknown", server_default="Unknown"
    )
    expected_salary_basis: Mapped[str] = mapped_column(
        Text, default="Unknown", server_default="Unknown"
    )
    last_salary_raw: Mapped[str | None] = mapped_column(Text)
    notice_period_text: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class CandidateVisit(Identity, Base):
    __tablename__ = "candidate_visits"
    __table_args__ = (
        CheckConstraint("length(btrim(purpose))>0", name="ck_candidate_visit_purpose"),
        CheckConstraint(
            "authority_status IN ('Not recorded','Pending','Signed (reported)','Not signed')",
            name="ck_candidate_visit_authority",
        ),
        Index("ix_candidate_visit_timeline", "candidate_id", "visited_at"),
        Index("ix_candidate_visit_day", "visited_at"),
    )
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id", ondelete="RESTRICT"))
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str] = mapped_column(Text)
    recorded_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    authority_status: Mapped[str] = mapped_column(
        Text, default="Not recorded", server_default="Not recorded"
    )
    note: Mapped[str | None] = mapped_column(Text)


class JobSearchRequest(Identity, Updated, Base):
    __tablename__ = "job_search_requests"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(desired_role))>0 AND version>0", name="ck_search_role_version"
        ),
        CheckConstraint(
            "status IN ('Searching','Interviewing','On Hold','Placed','Closed')",
            name="ck_search_status",
        ),
        CheckConstraint(
            "(status IN ('Placed','Closed')) = (closed_at IS NOT NULL)", name="ck_search_closed"
        ),
        CheckConstraint(
            "array_position(preferred_locations,NULL) IS NULL", name="ck_search_locations"
        ),
        Index("ix_search_assignee_due", "assigned_staff_id", "status", "follow_up_date"),
        Index("ix_search_candidate", "candidate_id"),
    )
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id", ondelete="RESTRICT"))
    desired_role: Mapped[str] = mapped_column(Text)
    preferred_locations: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    assigned_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(Text, default="Searching", server_default="Searching")
    next_action: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class CandidateDocument(Identity, Base):
    __tablename__ = "candidate_documents"
    __table_args__ = (
        UniqueConstraint("candidate_id", "kind", "version", name="uq_document_version"),
        UniqueConstraint("storage_key", name="uq_document_storage"),
        UniqueConstraint("id", "candidate_id", name="uq_document_candidate"),
        UniqueConstraint("id", "kind", name="uq_document_kind"),
        ForeignKeyConstraint(
            ["source_document_id", "candidate_id"],
            ["candidate_documents.id", "candidate_documents.candidate_id"],
            name="fk_document_source_candidate",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "kind IN ('ORIGINAL_RESUME','MODIFIED_RESUME','AUTHORITY')", name="ck_document_kind"
        ),
        CheckConstraint(
            (
                "(kind='MODIFIED_RESUME' AND source_document_id IS NOT NULL AND approval_s"
                "tatus='Reviewed') OR (kind<>'MODIFIED_RESUME' AND source_document_id IS N"
                "ULL)"
            ),
            name="ck_document_lineage",
        ),
        CheckConstraint(
            "source_document_id IS NULL OR source_document_id<>id", name="ck_document_not_self"
        ),
        CheckConstraint(
            "size_bytes>0 AND version>0 AND sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_integrity"
        ),
        CheckConstraint(
            (
                "content_type IN ('application/pdf','application/vnd.openxmlformats-office"
                "document.wordprocessingml.document')"
            ),
            name="ck_document_content_type",
        ),
    )
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    uploaded_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(Integer)
    source_document_id: Mapped[UUID | None] = mapped_column(Uuid)
    approval_status: Mapped[str | None] = mapped_column(Text)


class ResumeParseResult(Identity, Base):
    __tablename__ = "resume_parse_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "document_kind"],
            ["candidate_documents.id", "candidate_documents.kind"],
            name="fk_parse_original_document",
            ondelete="RESTRICT",
        ),
        CheckConstraint("document_kind='ORIGINAL_RESUME'", name="ck_parse_original"),
        CheckConstraint("provider IN ('ChatGPT','Claude')", name="ck_parse_provider"),
        CheckConstraint("jsonb_typeof(parsed_json)='object'", name="ck_parse_object"),
        CheckConstraint("validation_status='Structurally checked'", name="ck_parse_validation"),
        CheckConstraint("schema_version=1", name="ck_parse_schema"),
        CheckConstraint(
            (
                "(review_status='Unreviewed' AND reviewed_at IS NULL AND reviewed_by_staff"
                "_id IS NULL) OR (review_status IN ('Reviewed','Rejected') AND reviewed_at"
                " IS NOT NULL AND reviewed_by_staff_id IS NOT NULL)"
            ),
            name="ck_parse_review",
        ),
        Index("ix_parse_document_time", "document_id", "created_at"),
    )
    document_id: Mapped[UUID] = mapped_column(Uuid)
    document_kind: Mapped[str] = mapped_column(
        Text, default="ORIGINAL_RESUME", server_default="ORIGINAL_RESUME"
    )
    provider: Mapped[str] = mapped_column(Text)
    model_label: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    parsed_json: Mapped[dict] = mapped_column(JSONB)
    validation_status: Mapped[str] = mapped_column(
        Text, default="Structurally checked", server_default="Structurally checked"
    )
    review_status: Mapped[str] = mapped_column(
        Text, default="Unreviewed", server_default="Unreviewed"
    )
    pasted_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    reviewed_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


STAGE3_MODELS = (
    WorkDomain,
    WorkSubdomain,
    Candidate,
    CandidateVisit,
    JobSearchRequest,
    CandidateDocument,
    ResumeParseResult,
)
STAGE3_TABLES = frozenset(model.__tablename__ for model in STAGE3_MODELS)


class CandidateResume(Base):
    """Immutable original bytes with independent, nullable future parser output."""

    __tablename__ = "candidate_resumes"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_candidate_resume_storage"),
        Index(
            "uq_candidate_resume_active",
            "candidate_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_candidate_resume_history", "candidate_id", "uploaded_at"),
        CheckConstraint(
            "file_size > 0 AND file_hash ~ '^[0-9a-f]{64}$'", name="ck_candidate_resume_integrity"
        ),
        CheckConstraint(
            "parsing_status IN ('not_parsed','processing','parsed','failed')",
            name="ck_candidate_resume_parsing",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id", ondelete="RESTRICT"))
    original_filename: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(Integer)
    file_hash: Mapped[str] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    parsed_json: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    parsing_status: Mapped[str] = mapped_column(Text, server_default="not_parsed")
    parsing_error: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


CANDIDATE_RESUME_TABLES = frozenset({"candidate_resumes"})

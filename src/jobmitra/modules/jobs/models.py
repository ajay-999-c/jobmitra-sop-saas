from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from jobmitra.core.database import Base
from jobmitra.modules.jobs.focus import FOCUS_CHECK


class JobRequirement(Base):
    __tablename__ = "job_requirements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["subdomain_id", "domain_id"],
            ["work_subdomains.id", "work_subdomains.domain_id"],
            name="fk_job_subdomain_parent",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "subdomain_id IS NULL OR domain_id IS NOT NULL", name="ck_job_subdomain_domain"
        ),
        CheckConstraint(FOCUS_CHECK, name="ck_job_work_focus"),
        CheckConstraint("length(btrim(job_title)) > 0", name="ck_job_title_nonblank"),
        CheckConstraint("status IN ('Draft','Active','On Hold','Closed')", name="ck_job_status"),
        CheckConstraint(
            "salary_period IN ('Monthly','Annual','Unknown')", name="ck_job_salary_period"
        ),
        CheckConstraint(
            "salary_basis IN ('CTC','Gross','Take-home','Unknown')", name="ck_job_salary_basis"
        ),
        CheckConstraint(
            "experience_min_months >= 0 AND experience_max_months >= 0",
            name="ck_job_experience_nonnegative",
        ),
        CheckConstraint(
            "experience_min_months <= experience_max_months", name="ck_job_experience_order"
        ),
        CheckConstraint(
            "salary_min >= 0 AND salary_max >= 0 AND salary_min <> 'NaN'::numeric AND "
            "salary_max <> 'NaN'::numeric",
            name="ck_job_salary_nonnegative",
        ),
        CheckConstraint("salary_min <= salary_max", name="ck_job_salary_order"),
        CheckConstraint("vacancies > 0", name="ck_job_vacancies_positive"),
        CheckConstraint("specific_skill_min_months >= 0", name="ck_job_specific_months"),
        CheckConstraint("version > 0", name="ck_job_version"),
        CheckConstraint(
            "array_position(required_skills,NULL) IS NULL AND "
            "array_position(preferred_skills,NULL) IS NULL",
            name="ck_job_skills_no_nulls",
        ),
        CheckConstraint(
            "target_milestone IN ('SHORTLIST','SELECTION','JOINING')",
            name="ck_job_target_milestone",
        ),
        CheckConstraint(
            "(target_date IS NULL) = (target_milestone IS NULL)", name="ck_job_target_pair"
        ),
        CheckConstraint(
            "(target_completed_at IS NULL AND target_completed_by_staff_id IS NULL) OR "
            "(target_completed_at IS NOT NULL AND target_completed_by_staff_id IS NOT "
            "NULL AND target_milestone IS NOT NULL AND target_milestone='SHORTLIST')",
            name="ck_job_shortlist_confirmation",
        ),
        CheckConstraint(
            "(status='Closed' AND closed_at IS NOT NULL AND closed_by_staff_id IS NOT "
            "NULL AND closure_reason IS NOT NULL AND length(btrim(closure_reason))>0) OR "
            "(status<>'Closed' AND closed_at IS NULL AND closed_by_staff_id IS NULL AND "
            "closure_reason IS NULL)",
            name="ck_job_closure",
        ),
        CheckConstraint(
            "(ats_json IS NULL AND ats_schema_version IS NULL AND ats_status='Not Added')"
            " OR (ats_json IS NOT NULL AND ats_schema_version IS NOT NULL AND "
            "ats_schema_version=1 AND ats_status IN ('Draft','Reviewed','Stale'))",
            name="ck_job_ats_state",
        ),
        CheckConstraint(
            "array_position(general_skills,NULL) IS NULL", name="ck_job_general_skills_no_nulls"
        ),
        Index("ix_job_company_status", "company_id", "status"),
        Index("ix_job_status", "status"),
        Index("ix_job_target", "target_date", postgresql_where=text("target_date IS NOT NULL")),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", name="fk_job_company", ondelete="RESTRICT")
    )
    company_contact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("company_contacts.id", name="fk_job_contact", ondelete="RESTRICT")
    )
    created_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    job_title: Mapped[str] = mapped_column(Text)
    raw_requirement: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    domain_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("work_domains.id", name="fk_job_domain", ondelete="RESTRICT")
    )
    subdomain_id: Mapped[UUID | None] = mapped_column(Uuid)
    domain_key: Mapped[str | None] = mapped_column(Text)
    subdomain_key: Mapped[str | None] = mapped_column(Text)
    location_text: Mapped[str | None] = mapped_column(Text)
    work_mode: Mapped[str | None] = mapped_column(Text)
    experience_min_months: Mapped[int | None] = mapped_column(Integer)
    experience_max_months: Mapped[int | None] = mapped_column(Integer)
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_period: Mapped[str] = mapped_column(Text, default="Unknown", server_default="Unknown")
    salary_basis: Mapped[str] = mapped_column(Text, default="Unknown", server_default="Unknown")
    salary_currency: Mapped[str | None] = mapped_column(Text)
    vacancies: Mapped[int | None] = mapped_column(Integer)
    qualification: Mapped[str | None] = mapped_column(Text)
    general_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    required_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    preferred_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    specific_skill: Mapped[str | None] = mapped_column(Text)
    specific_skill_min_months: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="Draft", server_default="Draft")
    current_work_focus: Mapped[str | None] = mapped_column(Text)
    target_date: Mapped[date | None] = mapped_column(Date)
    target_milestone: Mapped[str | None] = mapped_column(Text)
    target_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target_completed_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    ats_json: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    ats_schema_version: Mapped[int | None] = mapped_column(SmallInteger)
    ats_status: Mapped[str] = mapped_column(Text, default="Not Added", server_default="Not Added")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    closure_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobRecruiter(Base):
    __tablename__ = "job_recruiters"
    __table_args__ = (
        CheckConstraint(
            "removed_at IS NULL OR removed_at >= assigned_at", name="ck_recruiter_dates"
        ),
        Index(
            "ix_recruiter_active_staff",
            "staff_id",
            "job_id",
            postgresql_where=text("removed_at IS NULL"),
        ),
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_requirements.id", ondelete="RESTRICT"), primary_key=True
    )
    staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

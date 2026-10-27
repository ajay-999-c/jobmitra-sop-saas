import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from jobmitra.core.validation import InputModel, Nonnegative, Positive, ReadModel, skills
from jobmitra.modules.jobs.focus import WorkFocus

Status = Literal["Draft", "Active", "On Hold", "Closed"]
Milestone = Literal["SHORTLIST", "SELECTION", "JOINING"]
SalaryPeriod = Literal["Monthly", "Annual", "Unknown"]
SalaryBasis = Literal["CTC", "Gross", "Take-home", "Unknown"]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]


class RecordedAction(InputModel):
    actor_staff_id: UUID
    version: Positive


class OptionalCriteria(InputModel):
    company_id: UUID | None = None
    company_contact_id: UUID | None = None
    job_title: str | None = Field(default=None, min_length=1, max_length=300)
    raw_requirement: str | None = None
    received_at: AwareDatetime | None = None
    domain_id: UUID | None = None
    subdomain_id: UUID | None = None
    domain_key: str | None = None
    subdomain_key: str | None = None
    location_text: str | None = None
    work_mode: str | None = None
    experience_min_months: Nonnegative | None = None
    experience_max_months: Nonnegative | None = None
    salary_min: Money | None = None
    salary_max: Money | None = None
    salary_period: SalaryPeriod | None = None
    salary_basis: SalaryBasis | None = None
    salary_currency: str | None = None
    vacancies: Positive | None = None
    qualification: str | None = None
    general_skills: list[str] | None = None
    required_skills: list[str] | None = None
    preferred_skills: list[str] | None = None
    specific_skill: str | None = None
    specific_skill_min_months: Nonnegative | None = None

    @field_validator("general_skills", mode="before")
    @classmethod
    def normalize_general_skills(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("Skills must be text or a list of text values")
        return skills(
            [part for item in value for part in re.split(r"[,\r\n]", item) if part.strip()]
        )

    @field_validator("required_skills", "preferred_skills", mode="before")
    @classmethod
    def dedupe_skills(cls, value):
        return skills(value) if value is not None else None

    @field_validator(
        "raw_requirement",
        "domain_key",
        "subdomain_key",
        "location_text",
        "work_mode",
        "salary_currency",
        "qualification",
        "specific_skill",
        mode="before",
    )
    @classmethod
    def blank_is_missing(cls, value):
        return value.strip() or None if isinstance(value, str) else value


class ManualCriteria(OptionalCriteria):
    company_id: UUID
    job_title: str = Field(min_length=1, max_length=300)
    salary_period: SalaryPeriod = "Unknown"
    salary_basis: SalaryBasis = "Unknown"
    general_skills: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered_ranges(self):
        for lower, upper in [
            (self.experience_min_months, self.experience_max_months),
            (self.salary_min, self.salary_max),
        ]:
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("Minimum must not exceed maximum")
        return self


class JobCreate(ManualCriteria):
    salary_currency: str | None = "INR"
    actor_staff_id: UUID
    status: Status = "Draft"
    target_date: date | None = None
    target_milestone: Milestone | None = None
    closure_reason: str | None = None

    @model_validator(mode="after")
    def valid_tracking(self):
        if (self.target_date is None) != (self.target_milestone is None):
            raise ValueError("Target date and milestone must be entered together")
        if self.status == "Closed" and not (self.closure_reason or "").strip():
            raise ValueError("A closure reason is required")
        if self.status != "Closed" and self.closure_reason is not None:
            raise ValueError("A closure reason belongs only to a Closed JD")
        return self


class JobPatch(OptionalCriteria, RecordedAction):
    pass


class RecruiterUpdate(RecordedAction):
    staff_ids: list[UUID]

    @field_validator("staff_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Recruiter IDs must be unique")
        return value


class WorkFocusPatch(RecordedAction):
    current_work_focus: WorkFocus | None

    @field_validator("current_work_focus", mode="before")
    @classmethod
    def empty_is_clear(cls, value):
        return None if value == "" else value


class TargetPatch(RecordedAction):
    target_date: date | None
    target_milestone: Milestone | None

    @model_validator(mode="after")
    def paired(self):
        if (self.target_date is None) != (self.target_milestone is None):
            raise ValueError("Target date and milestone must be changed together")
        return self


class StatusPatch(RecordedAction):
    status: Status
    closure_reason: str | None = None

    @model_validator(mode="after")
    def reason(self):
        if self.status == "Closed" and not (self.closure_reason or "").strip():
            raise ValueError("A closure reason is required")
        if self.status != "Closed" and self.closure_reason is not None:
            raise ValueError("A closure reason belongs only to a Closed JD")
        return self


class ATSJsonV1(InputModel):
    schema_version: Literal[1] = 1
    keywords: list[str]
    suggested_required_skills: list[str]
    suggested_preferred_skills: list[str]
    semantic_summary: str
    professional_jd: str

    @field_validator(
        "keywords", "suggested_required_skills", "suggested_preferred_skills", mode="before"
    )
    @classmethod
    def unique_text(cls, value):
        return skills(value)


class ATSUpdate(RecordedAction):
    ats: ATSJsonV1
    reviewed: bool = False


class JobRead(ManualCriteria, ReadModel):
    current_work_focus: WorkFocus | None
    id: UUID
    company_name: str
    created_by_staff_id: UUID
    status: Status
    target_date: date | None
    target_milestone: Milestone | None
    target_completed_at: datetime | None
    target_completed_by_staff_id: UUID | None
    target_state: str
    target_verification: str | None
    ats_json: dict | None
    ats_schema_version: int | None
    ats_status: str
    closed_at: datetime | None
    closed_by_staff_id: UUID | None
    closure_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    recruiters: list[dict]

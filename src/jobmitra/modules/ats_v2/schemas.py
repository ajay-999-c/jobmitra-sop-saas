"""Explicit input contracts; legacy PostgreSQL models are never used for ATS writes."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

Period = Literal["MONTHLY", "ANNUAL"]
Basis = Literal["UNKNOWN", "CTC", "GROSS", "IN_HAND"]
Stage = Literal[
    "POOL",
    "CONTACT",
    "SCREENING",
    "COMPANY_SUBMISSION",
    "ROUND",
    "SELECTED",
    "JOINED",
    "NOT_SELECTED",
]
FeedbackSource = Literal["COMPANY", "JOBMITRA", "CANDIDATE", "NOT_SPECIFIED"]


def _round_key(value):
    # Imported rounds use opaque stable stage keys (e.g. 1-r1), not only UUIDs.
    if isinstance(value, UUID):
        value = str(value)
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use the canonical interview-round key returned by this JD")
    return value


RoundKey = Annotated[str, Field(min_length=1, max_length=200), BeforeValidator(_round_key)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class JobCreate(Input):
    company_id: UUID
    assigned_recruiter_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    target_date: date
    company_contact: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    work_mode: Literal["ONSITE", "HYBRID", "REMOTE"] | None = None
    vacancies: int | None = Field(default=None, ge=1, le=100000)
    status: Literal["DRAFT", "ACTIVE", "ON_HOLD", "CLOSED"] = "ACTIVE"
    skills: list[str] = Field(default_factory=list, max_length=100)
    experience_min: float | None = Field(default=None, ge=0, le=80)
    experience_max: float | None = Field(default=None, ge=0, le=80)
    qualification: str | None = Field(default=None, max_length=1000)
    salary_min_inr: int | None = Field(default=None, ge=0, le=10**12)
    salary_max_inr: int | None = Field(default=None, ge=0, le=10**12)
    salary_period: Period | None = None
    salary_basis: Basis = "UNKNOWN"
    requirement_notes: str | None = Field(default=None, max_length=20000)
    full_jd: str | None = Field(default=None, max_length=100000)

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, values):
        if any(not v.strip() or len(v) > 150 for v in values):
            raise ValueError("Skills must be nonempty and at most 150 characters each.")
        return list(dict.fromkeys(v.strip() for v in values))

    @model_validator(mode="after")
    def ranges(self):
        for low, high in [
            (self.experience_min, self.experience_max),
            (self.salary_min_inr, self.salary_max_inr),
        ]:
            if low is not None and high is not None and low > high:
                raise ValueError("Range minimum must not exceed its maximum.")
        return self


class JobPatch(Input):
    assigned_recruiter_id: UUID | None = None
    expected_revision: str | None = Field(default=None, min_length=64, max_length=64)
    company_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    target_date: date | None = None
    company_contact: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    work_mode: Literal["ONSITE", "HYBRID", "REMOTE"] | None = None
    vacancies: int | None = Field(default=None, ge=1, le=100000)
    status: Literal["DRAFT", "ACTIVE", "ON_HOLD", "CLOSED"] | None = None
    skills: list[str] | None = Field(default=None, max_length=100)
    experience_min: float | None = Field(default=None, ge=0, le=80)
    experience_max: float | None = Field(default=None, ge=0, le=80)
    qualification: str | None = Field(default=None, max_length=1000)
    salary_min_inr: int | None = Field(default=None, ge=0, le=10**12)
    salary_max_inr: int | None = Field(default=None, ge=0, le=10**12)
    salary_period: Period | None = None
    salary_basis: Basis | None = None
    requirement_notes: str | None = Field(default=None, max_length=20000)
    full_jd: str | None = Field(default=None, max_length=100000)

    @model_validator(mode="after")
    def required_values(self):
        for key in ("company_id", "title", "target_date", "status", "skills", "salary_basis"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null.")
        return self


class RoundInput(Input):
    id: RoundKey | None = None
    round_name: str = Field(min_length=3, max_length=80)
    mode: Literal["FLEXIBLE", "FACE_TO_FACE", "VIDEO", "PHONE"] = "FLEXIBLE"
    is_active: bool = True


class WorkflowInput(Input):
    workflow_mode: Literal["UNKNOWN", "DIRECT", "CONFIGURED"]
    workflow_version: int = Field(ge=0)
    rounds: list[RoundInput] = Field(default_factory=list, max_length=100)


class LinkInput(Input):
    candidate_id: int = Field(ge=1)


class MoveInput(Input):
    stage_code: Stage
    round_id: RoundKey | None = None
    feedback: str | None = Field(default=None, max_length=1500)
    feedback_source: FeedbackSource = "NOT_SPECIFIED"
    expected_stage: Stage | None = None
    expected_round_id: RoundKey | None = None
    workflow_version: int | None = Field(default=None, ge=0)


class FeedbackInput(Input):
    feedback: str = Field(min_length=1, max_length=1500)
    feedback_source: FeedbackSource = "NOT_SPECIFIED"
    stage_code: Stage | None = None
    round_id: RoundKey | None = None


class ActivityInput(Input):
    job_id: int | None = Field(default=None, ge=1)
    activity_type: Literal[
        "FOLLOW_UP",
        "OFFICE_VISIT",
        "JOB_SEARCH_REQUEST",
        "CALL",
        "INTERVIEW",
        "CANDIDATE_SUBMISSION",
        "OTHER",
    ] = "FOLLOW_UP"
    status: Literal["OPEN", "DONE", "CANCELLED"] = "OPEN"
    due_at: datetime | None = None
    occurred_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("due_at", "occurred_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Include a timezone offset for activity timestamps.")
        return value


class ActivityPatch(ActivityInput):
    # The service merges explicitly submitted fields over the stored activity.
    pass

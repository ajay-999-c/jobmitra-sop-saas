import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, field_validator

from jobmitra.core.validation import InputModel, Nonnegative, Positive, ReadModel, skills

from .constants import (
    STATES,
    UNION_TERRITORIES,
    AuthorityStatus,
    RequestStatus,
    SalaryBasis,
    SalaryPeriod,
    Source,
)

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
Name = Annotated[str, Field(min_length=1, max_length=300)]


def normalized_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def mobile_key(value):
    if not re.fullmatch(r"[0-9+() .-]+", value):
        raise ValueError("Use a mobile number with 8–15 digits")
    digits = re.sub("[^0-9]", "", value)
    if not 8 <= len(digits) <= 15:
        raise ValueError("Use a mobile number with 8–15 digits")
    return digits


class CandidateFields(InputModel):
    full_name: Name | None = None
    mobile: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    source: Source | None = None
    role_title: str | None = Field(default=None, max_length=300)
    domain_id: UUID | None = None
    subdomain_id: UUID | None = None
    qualification: str | None = None
    experience_months: Nonnegative | None = None
    skills: list[str] | None = None
    current_location: str | None = None
    preferred_locations: list[str] | None = None
    hometown: str | None = None
    home_state: str | None = None
    ready_to_relocate: StrictBool | None = None
    current_salary_amount: Money | None = None
    current_salary_period: SalaryPeriod | None = None
    current_salary_basis: SalaryBasis | None = None
    expected_salary_amount: Money | None = None
    expected_salary_period: SalaryPeriod | None = None
    expected_salary_basis: SalaryBasis | None = None
    last_salary_raw: str | None = None
    notice_period_text: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def email_format(cls, value):
        if value is None or value == "":
            return None
        value = value.strip()
        if not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
            raise ValueError("Enter a valid email address or leave it empty")
        return value.lower()

    @field_validator("mobile")
    @classmethod
    def mobile_format(cls, value):
        if value is not None:
            mobile_key(value)
        return value

    @field_validator("home_state")
    @classmethod
    def state_choice(cls, value):
        if value is not None and value not in STATES + UNION_TERRITORIES:
            raise ValueError("Choose one of the 28 states or 8 union territories")
        return value

    @field_validator("skills", "preferred_locations", mode="before")
    @classmethod
    def distinct_values(cls, value):
        return skills(value) if value is not None else None


class CandidateProfile(CandidateFields):
    full_name: Name
    mobile: str = Field(min_length=1, max_length=40)
    source: Source
    skills: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    current_salary_period: SalaryPeriod = "Unknown"
    current_salary_basis: SalaryBasis = "Unknown"
    expected_salary_period: SalaryPeriod = "Unknown"
    expected_salary_basis: SalaryBasis = "Unknown"


class JobSearchRequestCreate(InputModel):
    desired_role: Name
    preferred_locations: list[str] = Field(default_factory=list)
    assigned_staff_id: UUID
    status: RequestStatus = "Searching"
    next_action: str | None = None
    follow_up_date: date | None = None
    note: str | None = None

    @field_validator("preferred_locations", mode="before")
    @classmethod
    def distinct_locations(cls, value):
        return skills(value)


class CandidateCreate(CandidateProfile):
    confirm_duplicate: bool = False
    recorded_by_staff_id: UUID | None = None
    initial_job_search: JobSearchRequestCreate | None = None


class CandidatePatch(CandidateFields):
    version: Positive
    confirm_duplicate: bool = False


class CandidateRead(CandidateProfile, ReadModel):
    id: UUID
    mobile_normalized: str
    version: int
    created_at: datetime
    updated_at: datetime


class VisitCreate(InputModel):
    visited_at: AwareDatetime
    purpose: Name
    recorded_by_staff_id: UUID | None = None
    authority_status: AuthorityStatus = "Not recorded"
    note: str | None = None


class VisitRead(VisitCreate, ReadModel):
    id: UUID
    candidate_id: UUID
    created_at: datetime


class JobSearchRequestPatch(InputModel):
    version: Positive
    desired_role: Name | None = None
    preferred_locations: list[str] | None = None
    assigned_staff_id: UUID | None = None
    status: RequestStatus | None = None
    next_action: str | None = None
    follow_up_date: date | None = None
    note: str | None = None


class JobSearchRequestRead(JobSearchRequestCreate, ReadModel):
    id: UUID
    candidate_id: UUID
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
    is_overdue: bool = False


class DomainCreate(InputModel):
    name: Name


class SubdomainCreate(DomainCreate):
    domain_id: UUID


class CatalogPatch(InputModel):
    name: Name | None = None
    is_active: StrictBool | None = None


class DomainRead(DomainCreate, ReadModel):
    id: UUID
    key: str
    normalized_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SubdomainRead(DomainRead):
    domain_id: UUID


class DocumentRead(ReadModel):
    id: UUID
    candidate_id: UUID
    kind: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
    uploaded_by_staff_id: UUID | None
    version: int
    source_document_id: UUID | None
    approval_status: str | None
    # storage_key is deliberately excluded from API responses.


class ResumeParseCreate(InputModel):
    document_id: UUID
    provider: Literal["ChatGPT", "Claude"]
    model_label: str | None = Field(default=None, max_length=200)
    parsed_json: dict
    pasted_by_staff_id: UUID | None = None

    @field_validator("parsed_json", mode="before")
    @classmethod
    def object_only(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Paste a JSON object")
        try:
            encoded = json.dumps(value, allow_nan=False)
        except (ValueError, TypeError, RecursionError):
            raise ValueError("Use a finite JSON object") from None
        if len(encoded.encode()) > 262144:
            raise ValueError("Parsed JSON exceeds 256 KiB")
        return value


class ResumeParseReview(InputModel):
    reviewed_by_staff_id: UUID
    review_status: Literal["Reviewed", "Rejected"]


class ResumeParseRead(ResumeParseCreate, ReadModel):
    id: UUID
    schema_version: int
    validation_status: str
    review_status: str
    reviewed_by_staff_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime

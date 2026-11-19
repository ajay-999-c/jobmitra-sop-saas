"""Inputs for the isolated SQLite candidate master; no legacy candidate writes."""

import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jobmitra.modules.candidates.schemas import mobile_key

Period = Literal["MONTHLY", "ANNUAL"]
Basis = Literal["UNKNOWN", "CTC", "GROSS", "IN_HAND"]
Availability = Literal["AVAILABLE", "TO_CONFIRM", "UNAVAILABLE"]
Text = Annotated[str, Field(max_length=1000)]


class CandidateFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    full_name: str | None = Field(default=None, min_length=1, max_length=300)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    links: dict[str, str] | None = None
    job_title: Text | None = None
    current_employer: Text | None = None
    current_city: Text | None = None
    preferred_cities: list[Text] | None = None
    experience_years: float | None = Field(default=None, ge=0, le=100)
    qualification: Text | None = None
    primary_domain: Text | None = None
    skills: list[Text] | None = None
    professional_summary: str | None = Field(default=None, max_length=20000)
    current_salary_inr: int | None = Field(default=None, ge=0, le=10**10)
    current_salary_period: Period | None = None
    current_salary_basis: Basis | None = None
    expected_salary_inr: int | None = Field(default=None, ge=0, le=10**10)
    expected_salary_period: Period | None = None
    expected_salary_basis: Basis | None = None
    notice_days: int | None = Field(default=None, ge=0, le=730)
    availability: Availability | None = None
    source: Literal["MANUAL", "WALK_IN", "FOUNDIT_PASTE", "RESUME_UPLOAD", "OTHER"] | None = None
    is_active: bool | None = None

    @field_validator("full_name")
    @classmethod
    def name(cls, value):
        if value is not None and (not value.strip() or any(ord(c) < 32 for c in value)):
            raise ValueError("Enter the candidate's original full name")
        return " ".join(value.split()) if value is not None else value

    @field_validator("phone", mode="before")
    @classmethod
    def phone_format(cls, value):
        if value in (None, ""):
            return None
        mobile_key(value)
        return value

    @field_validator("email", mode="before")
    @classmethod
    def email_format(cls, value):
        if value in (None, ""):
            return None
        if not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value.strip()):
            raise ValueError("Enter a valid email address")
        return value.strip().lower()

    @field_validator("skills", "preferred_cities")
    @classmethod
    def unique_items(cls, value):
        if value is None:
            return None
        if len(value) > 150:
            raise ValueError("Use at most 150 entries")
        result, seen = [], set()
        for item in value:
            key = item.strip().casefold()
            if key and key not in seen:
                result.append(item.strip())
                seen.add(key)
        return result

    @field_validator("links")
    @classmethod
    def professional_links(cls, value):
        if value is not None:
            if len(value) > 20:
                raise ValueError("Use at most 20 professional links")
            for label, url in value.items():
                if len(label) > 100 or len(url) > 2000 or not re.match(r"^https?://", url):
                    raise ValueError("Professional links must use http or https")
        return value


class CandidateCreate(CandidateFields):
    full_name: str = Field(min_length=1, max_length=300)
    skills: list[Text] = Field(default_factory=list)
    preferred_cities: list[Text] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)
    availability: Availability = "TO_CONFIRM"
    source: Literal["MANUAL", "WALK_IN", "FOUNDIT_PASTE", "RESUME_UPLOAD", "OTHER"] = "MANUAL"
    is_active: bool = True


class CandidatePatch(CandidateFields):
    @model_validator(mode="after")
    def mandatory_values(self):
        for field in (
            "full_name",
            "skills",
            "preferred_cities",
            "links",
            "availability",
            "source",
            "is_active",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class SearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    keywords: str = Field(default="", max_length=500)
    match: Literal["ANY", "ALL"] = "ANY"
    location: str = Field(default="", max_length=200)
    experience_min: float | None = Field(default=None, ge=0, le=100)
    experience_max: float | None = Field(default=None, ge=0, le=100)
    budget: int | None = Field(default=None, ge=0, le=10**10)
    salary_min: int | None = Field(default=None, ge=0, le=10**10)
    salary_max: int | None = Field(default=None, ge=0, le=10**10)
    salary_period: Period = "MONTHLY"
    salary_basis: Basis | Literal["INDICATIVE"] = "UNKNOWN"
    max_notice_days: int | None = Field(default=None, ge=0, le=730)
    availability: Availability | None = None
    include_unknown_experience: bool = True
    include_unknown_salary: bool = True
    include_unknown_notice: bool = True
    sort: Literal["relevance", "recent", "experience"] = "relevance"
    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def range_order(self):
        if (
            self.experience_min is not None
            and self.experience_max is not None
            and self.experience_min > self.experience_max
        ):
            raise ValueError("Minimum experience must not exceed maximum experience")
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("Minimum salary must not exceed maximum salary")
        return self


class ProfessionalProfile(BaseModel):
    """Professional evidence only; identity always comes from the candidate master."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    professional_summary: str | None = Field(default=None, max_length=20000)
    current_job_title: Text | None = None
    current_employer: Text | None = None
    skills: list[Text] = Field(default_factory=list, max_length=150)
    qualification: Text | None = None
    work_experience: list[dict] = Field(default_factory=list, max_length=100)
    education: list[dict | str] = Field(default_factory=list, max_length=100)
    projects: list[dict | str] = Field(default_factory=list, max_length=100)
    certifications: list[dict | str] = Field(default_factory=list, max_length=100)
    languages: list[Text] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def bounded_data(self):
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode()) > 256000:
            raise ValueError("Professional evidence exceeds the allowed size")
        return self


class ParsedResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: ProfessionalProfile
    source_resume_id: int = Field(ge=1)
    facts_reviewed: Literal[True]


class GenerateResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parsed_resume_id: int = Field(ge=1)
    facts_reviewed: Literal[True]

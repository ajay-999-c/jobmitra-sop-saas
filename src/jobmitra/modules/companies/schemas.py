"""Company UI payloads. IDs and spreadsheet references are never editable inputs."""

from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from jobmitra.modules.companies.normalization import company_name_key, distinct_text_values


class ContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None
    contact_name: str | None = None
    designation: str | None = None
    phone_numbers: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("phone_numbers")
    @classmethod
    def phones(cls, value):
        return distinct_text_values(value)


class CompanyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_name: str = Field(min_length=1, max_length=500)
    general_phone_numbers: list[str] = Field(default_factory=list, max_length=100)
    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    contacts: list[ContactInput] = Field(default_factory=list, max_length=100)

    @field_validator("company_name")
    @classmethod
    def name(cls, value):
        company_name_key(value)
        return value.strip()

    @field_validator("general_phone_numbers")
    @classmethod
    def phones(cls, value):
        return distinct_text_values(value)

    @field_validator("address_line", "city", "state", "postal_code")
    @classmethod
    def optional_text(cls, value):
        return value.strip() or None if value is not None else None


class CompanyUpdate(CompanyInput):
    updated_at: AwareDatetime
    # PUT replaces editable state; accidental omission must not delete contacts.
    contacts: list[ContactInput] = Field(max_length=100)


class CompanyVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    updated_at: AwareDatetime


class ContactDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    contact_name: str | None
    designation: str | None
    phone_numbers: list[str]


class CompanyDetail(BaseModel):
    id: UUID
    company_name: str
    general_phone_numbers: list[str]
    address_line: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    source_register_ids: list[str]
    created_at: datetime
    updated_at: datetime
    contacts: list[ContactDetail]

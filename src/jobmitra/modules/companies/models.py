"""The two Company Management tables; no AI or vector dependencies."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.types import Uuid

from jobmitra.core.database import Base
from jobmitra.modules.companies.normalization import company_name_key, distinct_text_values

COMPANY_TABLES = frozenset({"companies", "company_contacts"})


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("company_name_key", name="uq_companies_company_name_key"),
        CheckConstraint("length(btrim(company_name)) > 0", name="ck_companies_name_nonblank"),
        CheckConstraint("length(btrim(company_name_key)) > 0", name="ck_companies_key_nonblank"),
        CheckConstraint(
            "array_position(general_phone_numbers, NULL) IS NULL",
            name="ck_companies_phones_no_null_elements",
        ),
        CheckConstraint(
            "array_position(source_register_ids, NULL) IS NULL",
            name="ck_companies_sources_no_null_elements",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_name_key: Mapped[str] = mapped_column(Text, nullable=False)
    general_phone_numbers: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(ARRAY(Text)), default=list, server_default=text("'{}'::text[]")
    )
    address_line: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    source_register_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(ARRAY(Text)), default=list, server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    contacts: Mapped[list["CompanyContact"]] = relationship(
        back_populates="company", passive_deletes="all"
    )

    @validates("company_name")
    def validate_name(self, key: str, value: str) -> str:
        self.company_name_key = company_name_key(value)
        return value.strip()


class CompanyContact(Base):
    __tablename__ = "company_contacts"
    __table_args__ = (
        CheckConstraint(
            "array_position(phone_numbers, NULL) IS NULL",
            name="ck_company_contacts_phones_no_null_elements",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", name="fk_company_contacts_company", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    contact_name: Mapped[str | None] = mapped_column(Text)
    designation: Mapped[str | None] = mapped_column(Text)
    phone_numbers: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(ARRAY(Text)), default=list, server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    company: Mapped[Company] = relationship(back_populates="contacts")


@event.listens_for(Company, "before_insert")
@event.listens_for(Company, "before_update")
def prepare_company(mapper, connection, company: Company) -> None:
    company.company_name_key = company_name_key(company.company_name)
    company.general_phone_numbers = distinct_text_values(
        company.general_phone_numbers if company.general_phone_numbers is not None else []
    )
    company.source_register_ids = distinct_text_values(
        company.source_register_ids if company.source_register_ids is not None else []
    )


@event.listens_for(CompanyContact, "before_insert")
@event.listens_for(CompanyContact, "before_update")
def prepare_contact(mapper, connection, contact: CompanyContact) -> None:
    contact.phone_numbers = distinct_text_values(
        contact.phone_numbers if contact.phone_numbers is not None else []
    )

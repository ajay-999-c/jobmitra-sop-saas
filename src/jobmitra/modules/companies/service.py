"""Atomic Company UI changes using existing timestamps for stale-edit protection."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from jobmitra.modules.companies import repository
from jobmitra.modules.companies.models import Company, CompanyContact
from jobmitra.modules.companies.schemas import (
    CompanyDetail,
    CompanyInput,
    CompanyUpdate,
    ContactDetail,
)


class NotFound(Exception):
    pass


class StaleEdit(Exception):
    pass


class InvalidContact(Exception):
    pass


def require_company(session: Session, company_id: UUID, *, lock=False) -> Company:
    company = repository.find_company(session, company_id, lock=lock)
    if company is None:
        raise NotFound
    return company


def detail(session: Session, company: Company) -> CompanyDetail:
    values = {
        name: getattr(company, name) for name in CompanyDetail.model_fields if name != "contacts"
    }
    return CompanyDetail(
        **values,
        contacts=[
            ContactDetail.model_validate(contact)
            for contact in repository.company_contacts(session, company.id)
        ],
    )


def write(session: Session, data: CompanyInput, company_id: UUID | None = None) -> CompanyDetail:
    if company_id is None:
        if any(contact.id is not None for contact in data.contacts):
            raise InvalidContact
        company = Company(company_name=data.company_name)
        session.add(company)
        existing = {}
    else:
        company = require_company(session, company_id, lock=True)
        if not isinstance(data, CompanyUpdate) or company.updated_at != data.updated_at:
            raise StaleEdit
        existing = {c.id: c for c in repository.company_contacts(session, company.id)}
        ids = [c.id for c in data.contacts if c.id is not None]
        if len(ids) != len(set(ids)) or not set(ids) <= existing.keys():
            raise InvalidContact
        # Every child edit touches the parent token, serializing changes across devices.
        company.updated_at = max(datetime.now(UTC), company.updated_at + timedelta(microseconds=1))
    for name in (
        "company_name",
        "general_phone_numbers",
        "address_line",
        "city",
        "state",
        "postal_code",
    ):
        setattr(company, name, getattr(data, name))
    session.flush()
    retained = set()
    for values in data.contacts:
        if values.id is None:
            contact = CompanyContact(company_id=company.id)
            session.add(contact)
        else:
            contact = existing[values.id]
            retained.add(values.id)
        contact.contact_name = (values.contact_name or "").strip() or None
        contact.designation = (values.designation or "").strip() or None
        contact.phone_numbers = values.phone_numbers
    for contact_id, contact in existing.items():
        if contact_id not in retained:
            session.delete(contact)
    session.flush()
    result = detail(session, company)
    session.commit()
    return result


def delete(session: Session, company_id: UUID, updated_at: datetime) -> None:
    company = require_company(session, company_id, lock=True)
    if company.updated_at != updated_at:
        raise StaleEdit
    for contact in repository.company_contacts(session, company.id):
        session.delete(contact)
    session.flush()
    session.delete(company)
    session.commit()

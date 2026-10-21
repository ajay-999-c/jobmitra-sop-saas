"""Small PostgreSQL queries; directory snapshots deliberately exclude contacts and phones."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobmitra.modules.companies.models import Company, CompanyContact


def directory(session: Session) -> list[dict[str, str]]:
    rows = session.execute(
        select(Company.id, Company.company_name).order_by(Company.company_name_key, Company.id)
    )
    return [{"id": str(row.id), "company_name": row.company_name} for row in rows]


def find_company(session: Session, company_id: UUID, *, lock: bool = False) -> Company | None:
    query = select(Company).where(Company.id == company_id)
    return session.scalar(query.with_for_update() if lock else query)


def company_contacts(session: Session, company_id: UUID) -> list[CompanyContact]:
    return list(
        session.scalars(
            select(CompanyContact)
            .where(CompanyContact.company_id == company_id)
            .order_by(CompanyContact.created_at, CompanyContact.id)
        )
    )

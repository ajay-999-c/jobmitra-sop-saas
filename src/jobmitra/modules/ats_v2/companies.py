"""Read-only access to the imported Company Master in the ATS SQLite store.

The legacy Companies module still owns PostgreSQL edits. An explicit one-way
import synchronizes those records; ordinary ATS requests never connect to it.
"""

import json
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from .common import AtsError


class CompanyGateway:
    def __init__(self, engine):
        if engine.dialect.name not in {"sqlite", "postgresql"}:
            raise AtsError("ATS Company Master requires the configured SQLite store.", 503)
        self.sqlite_engine = engine

    def options(self):
        """Eligible companies only; return the same stable UUIDs used by imports."""
        try:
            with self.sqlite_engine.connect() as connection:
                return [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT id,company_name FROM companies WHERE is_active=1 "
                            "ORDER BY company_name_key,id"
                        )
                    ).mappings()
                ]
        except SQLAlchemyError:
            raise AtsError(
                "ATS Company Master is unavailable. Check the local database and retry.", 503
            ) from None

    def require(self, company_id):
        try:
            identifier = str(UUID(str(company_id)))
        except (ValueError, TypeError, AttributeError):
            raise AtsError("Select a valid company from the ATS Company Master.", 422) from None
        try:
            with self.sqlite_engine.connect() as connection:
                row = (
                    connection.execute(
                        text("SELECT id,company_name FROM companies WHERE id=:id AND is_active=1"),
                        {"id": identifier},
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise AtsError(
                        "Select an active company from the ATS Company Master. "
                        "New legacy companies appear after the next company import.",
                        422,
                    )
                return dict(row)
        except SQLAlchemyError:
            raise AtsError(
                "ATS Company Master is unavailable. The JD was not saved.", 503
            ) from None

    def names(self, company_ids):
        """Resolve historic references too, without making inactive companies eligible."""
        identifiers = list(dict.fromkeys(str(value) for value in company_ids))
        if not identifiers:
            return {}
        try:
            with self.sqlite_engine.connect() as connection:
                query = text("SELECT id,company_name FROM companies WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                )
                return dict(connection.execute(query, {"ids": identifiers}).all())
        except SQLAlchemyError:
            raise AtsError("ATS Company Master is unavailable. Retry loading the JD list.", 503)

    def detail(self, company_id):
        try:
            identifier = str(UUID(str(company_id)))
        except (ValueError, TypeError, AttributeError):
            raise AtsError("Invalid ATS company identifier.", 422) from None
        try:
            with self.sqlite_engine.connect() as connection:
                row = (
                    connection.execute(
                        text("SELECT * FROM companies WHERE id=:id"), {"id": identifier}
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise AtsError("ATS company not found.", 404)
                result = dict(row)
                result.pop("source_json", None)
                result.pop("source_fingerprint", None)
                for key in ("general_phone_numbers", "contacts", "source_register_ids"):
                    result[key] = json.loads(result.pop(key + "_json"))
                result["is_active"] = bool(result["is_active"])
                return result
        except SQLAlchemyError:
            raise AtsError(
                "ATS Company Master is unavailable. Retry loading its details.", 503
            ) from None


def resolve_companies(items, gateway):
    try:
        # Minimal test gateways may implement only the public options/require boundary.
        if callable(getattr(type(gateway), "names", None)):
            names = gateway.names(item["company_id"] for item in items)
        else:
            names = {company["id"]: company["company_name"] for company in gateway.options()}
    except AtsError as error:
        for item in items:
            item["company_name"] = None
        return error.message
    for item in items:
        item["company_name"] = names.get(item["company_id"])
        item["company_missing"] = item["company_id"] not in names
    return None

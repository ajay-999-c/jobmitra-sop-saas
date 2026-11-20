"""Read-only, company-scoped context for existing approved proposal composers."""

import json
from pathlib import Path

from sqlalchemy import text

from .common import AtsError

STUDIO_FILE = (
    Path(__file__).parents[1]
    / "email_studio"
    / "resources"
    / "Jobmitra_Company_Proposal_Studio.html"
)


def context(engine, company_id, contact_id=None):
    with engine.connect() as conn:
        row = (
            conn.execute(
                text("SELECT id,company_name,contacts_json FROM companies WHERE id=:id"),
                {"id": company_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise AtsError("Company not found.", 404)
        active = [c for c in json.loads(row["contacts_json"]) if not c.get("is_archived")]
        if contact_id:
            chosen = next((c for c in active if c["id"] == contact_id), None)
            if chosen is None:
                raise AtsError("Choose an active contact belonging to this company.", 422)
        else:
            chosen = (
                next((c for c in active if c.get("is_primary_email") and c.get("email")), None)
                or next((c for c in active if c.get("email")), None)
                or next(iter(active), None)
            )
        return {
            "company_id": row["id"],
            "company_name": row["company_name"],
            "company_contact_id": chosen["id"] if chosen else None,
            "contact_name": (chosen.get("contact_name") or "") if chosen else "",
            "recipient_email": (chosen.get("email") or "") if chosen else "",
            "contacts": [
                {"id": c["id"], "name": c.get("contact_name") or "", "email": c.get("email") or ""}
                for c in active
            ],
            "history_available": False,
            "history": [],
            "delivery_enabled": False,
        }

"""Pure mappings from existing PostgreSQL snapshots to the isolated ATS master.

No query, file access, model inference, ID allocation or write occurs here. Source
facts are retained in canonical JSON; unavailable facts stay unknown. Issues are
codes suitable for private migration reports without printing personal values.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

PERIODS = {"Monthly": "MONTHLY", "Annual": "ANNUAL", "Unknown": None, None: None}
BASES = {
    "CTC": "CTC",
    "Gross": "GROSS",
    "Take-home": "IN_HAND",
    "Unknown": "UNKNOWN",
    None: "UNKNOWN",
}
STAFF_KEYS = {"actor_name", "actor_id", "staff_id", "employee_id", "user_id", "assigned_to"}


@dataclass(frozen=True)
class MappingResult:
    values: dict
    issues: tuple[str, ...] = ()
    blocking_issues: tuple[str, ...] = ()
    references: dict = field(default_factory=dict)

    @property
    def valid(self):
        return not self.blocking_issues


def json_safe(value):
    """Preserve supported snapshot values without introducing binary floats for money."""
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
            if str(key).casefold() not in STAFF_KEYS
            and not str(key).casefold().endswith(("_staff_id", "_employee_id", "_actor_id"))
        }
    if isinstance(value, (tuple, list)):
        return [json_safe(item) for item in value]
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return (
            value.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if value.tzinfo is not None
            else value.isoformat()
        )
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return str(value)
        return value
    raise TypeError("Unsupported snapshot value type")


def canonical_json(value):
    return json.dumps(
        json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def source_fingerprint(value):
    document = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


class _Mapping:
    def __init__(self):
        self.issues, self.blocking = [], []

    def issue(self, code, *, block=False):
        if code not in self.issues:
            self.issues.append(code)
        if block and code not in self.blocking:
            self.blocking.append(code)

    def uuid(self, value, field_name, *, required=True):
        if value is None and not required:
            return None
        try:
            return str(UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            self.issue(f"invalid_{field_name}", block=True)
            return None

    def timestamp(self, value, field_name, *, required=True):
        if value is None and not required:
            return None
        try:
            parsed = (
                value
                if isinstance(value, datetime)
                else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            )
            if parsed.tzinfo is None:
                raise ValueError
            return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError, OverflowError):
            self.issue(f"invalid_{field_name}", block=required)
            return None

    def text(self, value, field_name, *, required=False):
        if value is None and not required:
            return None
        if not isinstance(value, str) or (required and not value.strip()):
            self.issue(f"invalid_{field_name}", block=required)
            return None
        return value

    def array(self, value, field_name, *, deduplicate=False):
        if value is None:
            return []
        if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) for v in value):
            self.issue(f"invalid_{field_name}")
            return []
        if not deduplicate:
            return list(value)
        result, seen = [], set()
        for original in value:
            item = original.strip()
            if item and item.casefold() not in seen:
                seen.add(item.casefold())
                result.append(item)
        return result

    def money(self, value, field_name):
        if value is None:
            return None
        try:
            # Source NUMERIC values must never pass through a binary float.
            if isinstance(value, (bool, float)):
                raise ValueError
            amount = Decimal(str(value))
            if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
                raise ValueError
            return format(amount, "f")
        except (InvalidOperation, ValueError, TypeError):
            self.issue(f"invalid_{field_name}", block=True)
            return None

    def finish(self, values, source, references=None):
        document = canonical_json(source)
        values.update(source_json=document, source_fingerprint=source_fingerprint(document))
        return MappingResult(values, tuple(self.issues), tuple(self.blocking), references or {})


def _catalog(rows):
    if isinstance(rows, dict):
        return {
            str(key): (value if isinstance(value, dict) else {"id": key, "name": value})
            for key, value in rows.items()
        }
    return {str(row["id"]): row for row in rows}


def map_company(row, contacts=()):
    """Keep the PostgreSQL UUID and every available company/contact business fact."""
    mapping = _Mapping()
    identifier = mapping.uuid(row.get("id"), "company_id")
    selected = [
        dict(contact)
        for contact in contacts
        if str(contact.get("company_id")) == str(row.get("id"))
    ]
    selected.sort(key=lambda contact: str(contact.get("id", "")))
    for contact in selected:
        mapping.uuid(contact.get("id"), "company_contact_id")
        mapping.timestamp(contact.get("created_at"), "contact_created_at")
        mapping.timestamp(contact.get("updated_at"), "contact_updated_at")
    values = {
        "id": identifier,
        "legacy_postgres_id": identifier,
        "company_name": mapping.text(row.get("company_name"), "company_name", required=True),
        "company_name_key": mapping.text(
            row.get("company_name_key"), "company_name_key", required=True
        ),
        "general_phone_numbers_json": canonical_json(
            mapping.array(row.get("general_phone_numbers"), "company_phone_numbers")
        ),
        "contacts_json": canonical_json(selected),
        "source_register_ids_json": canonical_json(
            mapping.array(row.get("source_register_ids"), "source_register_ids")
        ),
        "is_active": 1,
        "created_at": mapping.timestamp(row.get("created_at"), "company_created_at"),
        "updated_at": mapping.timestamp(row.get("updated_at"), "company_updated_at"),
    }
    for key in ("address_line", "city", "state", "postal_code"):
        values[key] = mapping.text(row.get(key), key)
    return mapping.finish(values, {**dict(row), "contacts": selected})


def _notice(value, mapping):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        mapping.issue("notice_unparsed")
        return None
    text_value = value.strip().casefold()
    if text_value in {"immediate", "immediately", "0"}:
        return 0
    match = re.fullmatch(r"(\d+)\s+days?", text_value)
    if match:
        return int(match.group(1))
    mapping.issue("notice_unparsed")
    return None


def map_candidate(row, domains=(), subdomains=()):
    """Map actual Candidate Desk fields; absent employer/summary/link facts stay absent."""
    mapping = _Mapping()
    identifier = mapping.uuid(row.get("id"), "candidate_id")
    domain_lookup, subdomain_lookup = _catalog(domains), _catalog(subdomains)
    domain = domain_lookup.get(str(row.get("domain_id"))) if row.get("domain_id") else None
    subdomain = (
        subdomain_lookup.get(str(row.get("subdomain_id"))) if row.get("subdomain_id") else None
    )
    if row.get("domain_id") and not domain:
        mapping.issue("domain_not_found")
    if row.get("subdomain_id") and not subdomain:
        mapping.issue("subdomain_not_found")
    if subdomain and str(subdomain.get("domain_id")) != str(row.get("domain_id")):
        mapping.issue("subdomain_parent_mismatch", block=True)
    phone = mapping.text(row.get("mobile"), "candidate_phone", required=True)
    normalized_phone = row.get("mobile_normalized")
    if not isinstance(normalized_phone, str) or not re.fullmatch(r"[0-9]{8,15}", normalized_phone):
        mapping.issue("invalid_candidate_phone_normalized", block=True)
        normalized_phone = None
    elif len(normalized_phone) == 10:
        normalized_phone = "91" + normalized_phone
    email = mapping.text(row.get("email"), "candidate_email")
    if email and not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", email):
        mapping.issue("invalid_candidate_email")
    experience = row.get("experience_months")
    if experience is not None and (
        isinstance(experience, bool) or not isinstance(experience, int) or experience < 0
    ):
        mapping.issue("invalid_experience_months", block=True)
        experience = None
    values = {
        "candidate_code": "PG-" + identifier.replace("-", "").upper() if identifier else None,
        "legacy_postgres_id": identifier,
        "full_name": mapping.text(row.get("full_name"), "candidate_name", required=True),
        "phone": phone,
        "phone_normalized": normalized_phone,
        "email": email,
        "email_normalized": email.strip().casefold() if email else None,
        "job_title": mapping.text(row.get("role_title"), "job_title"),
        "current_city": mapping.text(row.get("current_location"), "current_city"),
        "preferred_cities_json": canonical_json(
            mapping.array(row.get("preferred_locations"), "preferred_locations", deduplicate=True)
        ),
        "skills_json": canonical_json(mapping.array(row.get("skills"), "skills", deduplicate=True)),
        "qualification": mapping.text(row.get("qualification"), "qualification"),
        "experience_years": experience / 12 if experience is not None else None,
        "primary_domain": domain.get("name") if domain else None,
        "notice_days": _notice(row.get("notice_period_text"), mapping),
        "availability": "TO_CONFIRM",
        "is_active": 1,
        "links_json": "{}",
        "current_employer": None,
        "professional_summary": None,
        "source": {"Walk-in": "WALK_IN", "Foundit": "FOUNDIT_PASTE"}.get(
            row.get("source"), "OTHER"
        ),
        "created_at": mapping.timestamp(row.get("created_at"), "candidate_created_at"),
        "updated_at": mapping.timestamp(row.get("updated_at"), "candidate_updated_at"),
    }
    for prefix in ("current", "expected"):
        values[f"{prefix}_salary_inr"] = mapping.money(
            row.get(f"{prefix}_salary_amount"), f"{prefix}_salary_amount"
        )
        period, basis = row.get(f"{prefix}_salary_period"), row.get(f"{prefix}_salary_basis")
        if period not in PERIODS:
            mapping.issue(f"unknown_{prefix}_salary_period")
        if basis not in BASES:
            mapping.issue(f"unknown_{prefix}_salary_basis")
        values[f"{prefix}_salary_period"] = PERIODS.get(period)
        values[f"{prefix}_salary_basis"] = BASES.get(basis, "UNKNOWN")
    source = {**dict(row), "_resolved_catalog": {"domain": domain, "subdomain": subdomain}}
    return mapping.finish(values, source)


def map_resume_metadata(row, source_table, documents=()):
    """Map metadata without resolving storage roots, copying bytes or approving parses.

    Foreign identities are returned in ``references`` for explicit reconciliation
    by the orchestrator. Candidate Desk's two original-storage systems remain
    distinguished by ``legacy_source_table`` and their original source JSON.
    """
    mapping = _Mapping()
    if source_table not in {"candidate_documents", "candidate_resumes", "resume_parse_results"}:
        raise ValueError("Unsupported resume source table")
    identifier = mapping.uuid(row.get("id"), "resume_id")
    values = {
        "legacy_source_table": source_table,
        "legacy_postgres_id": identifier,
        "source_type": "UPLOADED",
        "is_current": 0,
        "storage_path": None,
        "raw_text": None,
        "parsed_json": None,
    }
    references = {}
    timestamp_field = "uploaded_at" if source_table == "candidate_resumes" else "created_at"
    values["created_at"] = mapping.timestamp(row.get(timestamp_field), "resume_created_at")
    if source_table == "resume_parse_results":
        document_id = mapping.uuid(row.get("document_id"), "source_document_id")
        document = _catalog(documents).get(document_id)
        if document is None:
            mapping.issue("source_document_not_found", block=True)
        elif document.get("kind") != "ORIGINAL_RESUME":
            mapping.issue("parse_source_not_original", block=True)
        references["document_id"] = document_id
        references["candidate_id"] = mapping.uuid(
            document.get("candidate_id") if document else None, "resume_candidate_id"
        )
        profile = row.get("parsed_json")
        if not isinstance(profile, dict):
            mapping.issue("invalid_parsed_resume_json", block=True)
        values.update(
            resume_kind="PARSED_TEXT",
            original_filename=None,
            parsed_json=canonical_json(profile) if isinstance(profile, dict) else None,
        )
        # A historical structural check is not a new factual approval.
        if row.get("review_status") != "Reviewed":
            mapping.issue("parsed_resume_requires_review")
    else:
        references["candidate_id"] = mapping.uuid(row.get("candidate_id"), "resume_candidate_id")
        references["storage_key"] = mapping.text(
            row.get("storage_key"), "resume_storage_key", required=True
        )
        filename = mapping.text(row.get("original_filename"), "resume_filename", required=True)
        if filename and (
            any(c in filename for c in '/\\:\x00<>"|?*')
            or filename.endswith((".", " "))
            or any(ord(c) < 32 for c in filename)
        ):
            mapping.issue("unsafe_resume_filename", block=True)
        expected_hash = (
            row.get("sha256") if source_table == "candidate_documents" else row.get("file_hash")
        )
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
            mapping.issue("invalid_resume_sha256", block=True)
        size = (
            row.get("size_bytes") if source_table == "candidate_documents" else row.get("file_size")
        )
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            mapping.issue("invalid_resume_size", block=True)
        content_type = (
            row.get("content_type")
            if source_table == "candidate_documents"
            else row.get("mime_type")
        )
        if content_type not in {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }:
            mapping.issue("unsupported_resume_content_type", block=True)
        kind = row.get("kind") if source_table == "candidate_documents" else "ORIGINAL_RESUME"
        if kind not in {"ORIGINAL_RESUME", "MODIFIED_RESUME"}:
            mapping.issue("unsupported_resume_kind", block=True)
        if kind == "MODIFIED_RESUME":
            references["source_document_id"] = mapping.uuid(
                row.get("source_document_id"), "source_document_id"
            )
            if row.get("approval_status") != "Reviewed":
                mapping.issue("standard_resume_requires_review", block=True)
        values.update(
            resume_kind="JOBMITRA_STANDARD" if kind == "MODIFIED_RESUME" else "ORIGINAL",
            original_filename=filename,
            parsed_json=canonical_json({"sha256": expected_hash, "size": size}),
        )
    return mapping.finish(values, row, references)

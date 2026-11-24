"""Native V12 adaptation of the existing deterministic Foundit parser. No network or writes."""

import hashlib
import re
from calendar import month_abbr
from decimal import Decimal

from pydantic import Field

from jobmitra.modules.candidates.foundit import parse_foundit_text
from jobmitra.modules.candidates.schemas import CandidateFields as LegacyFields

from .candidate_profiles import CompleteCreate, Strict, matches


class Paste(Strict):
    raw: str = Field(min_length=1, max_length=50000)


class V12FounditFields(LegacyFields):
    # Same parser/grammar; use the already supported V12 four-decimal salary contract.
    current_salary_amount: Decimal | None = Field(
        default=None, ge=0, le=10**10, max_digits=16, decimal_places=4
    )


def preview(engine, raw):
    text = re.sub(r"(?im)^\s*Current\s+Company\s*:", "Company:", raw)
    text = re.sub(r"(?im)^\s*Current\s+Designation\s*:", "Designation:", text)
    special = {}
    lines = []
    for line in text.splitlines():
        match = re.match(
            r"\s*(Expected\s+(?:CTC|salary)|(?:Professional\s+)?Summary|Functional\s+area|"
            r"Relevant\s+experience|Professional\s+qualifications?|Certifications?|Registration\s+purpose)"
            r"\s*[:：]\s*(.*)",
            line,
            re.I,
        )
        if match:
            special[match[1].lower()] = match[2]
        else:
            lines.append(line)
    parsed = parse_foundit_text("\n".join(lines), fields_model=V12FounditFields)
    old = parsed.fields.model_dump(exclude_none=True)
    mapping = {
        "full_name": "full_name",
        "mobile": "phone",
        "email": "email",
        "role_title": "job_title",
        "current_location": "current_city",
        "preferred_locations": "preferred_cities",
        "qualification": "qualification",
        "skills": "skills",
        "current_salary_amount": "current_salary_inr",
    }
    fields = {
        dest: str(old[src]) if src == "current_salary_amount" else old[src]
        for src, dest in mapping.items()
        if src in old
    }
    fields["source"] = "FOUNDIT_PASTE"
    period = {"Monthly": "MONTHLY", "Annual": "ANNUAL"}.get(old.get("current_salary_period"))
    if period:
        fields["current_salary_period"] = period
    if parsed.preview_only.get("employer"):
        fields["current_employer"] = parsed.preview_only["employer"]
    elif parsed.preview_only.get("employer_suggestion"):
        fields["current_employer"] = parsed.preview_only["employer_suggestion"]
    if parsed.preview_only.get("industry"):
        fields["primary_domain"] = parsed.preview_only["industry"]
    extra = {
        k: old[k]
        for k in ["notice_period_text", "experience_months", "ready_to_relocate"]
        if k in old
    }
    if "experience_months" in extra:
        fields["experience_years"] = extra["experience_months"] / 12
    unmapped = []
    for label, value in special.items():
        if "summary" in label:
            fields["professional_summary"] = value
        elif label == "functional area":
            extra["subdomain"] = value
        elif "qualification" in label:
            fields["qualification"] = "; ".join(filter(None, [fields.get("qualification"), value]))
        elif label == "registration purpose":
            extra["registration_purpose"] = value
        elif label.startswith("certification"):
            extra["certifications"] = [
                {"name": item.strip()} for item in re.split(r"[,;]", value) if item.strip()
            ]
        elif label == "relevant experience":
            unmapped.append(
                {
                    "field": "Relevant experience",
                    "value": value,
                    "reason": "No dedicated canonical field. Review and include it in "
                    "the professional summary if appropriate.",
                }
            )
        elif label.startswith("expected"):
            salary = parse_foundit_text(
                "Current CTC: " + value, fields_model=V12FounditFields
            ).fields
            if salary.current_salary_amount is not None:
                fields["expected_salary_inr"] = str(salary.current_salary_amount)
            period = {"Monthly": "MONTHLY", "Annual": "ANNUAL"}.get(salary.current_salary_period)
            if period:
                fields["expected_salary_period"] = period
            if "ctc" in label:
                fields["expected_salary_basis"] = "CTC"
    if re.search(r"(?im)^\s*(?:current\s+)?ctc\s*[:：]", raw):
        fields["current_salary_basis"] = "CTC"
    notice = extra.get("notice_period_text", "")
    if re.fullmatch(r"\d+\s*days?", notice, re.I):
        days = int(re.search(r"\d+", notice)[0])
        if days <= 730:
            fields["notice_days"] = days
    elif re.fullmatch(r"immediate(?:\s+joiner)?", notice, re.I):
        fields["notice_days"] = 0
    availability = re.search(
        r"(?im)^\s*Availability\s*[:：]\s*(Available|Unavailable|To confirm)\s*$", raw
    )
    if availability:
        fields["availability"] = availability[1].upper().replace(" ", "_")

    def month(value):
        match = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", value)
        months = {m.lower(): i for i, m in enumerate(month_abbr) if m}
        if match and match[1][:3].lower() in months:
            return f"{match[2]}-{months[match[1][:3].lower()]:02}"
        return None

    history = [
        dict(
            employer=e.employer, job_title=e.role, start_date=month(e.start), end_date=month(e.end)
        )
        for e in parsed.employment_history
        if e.role or e.employer
    ]
    if history:
        extra["employment_history"] = history
    if parsed.preview_only.get("past_industry"):
        unmapped.append(
            {
                "field": "Previous employer industry",
                "value": parsed.preview_only["past_industry"],
                "reason": "Employment history has no dedicated industry field; review this "
                "in the professional summary if needed.",
            }
        )
    if fields.get("qualification") and (
        parsed.preview_only.get("institution") or parsed.preview_only.get("education_year")
    ):
        education = {
            "qualification": fields["qualification"],
            "institution": parsed.preview_only.get("institution", ""),
        }
        year = parsed.preview_only.get("education_year", "")
        if re.fullmatch(r"(?:19|20)\d{2}", year):
            education["end_year"] = int(year)
        extra["education_history"] = [education]
    # Identity checks use normalized phone/email only; a name match alone is not a duplicate.
    person = CompleteCreate(**{**fields, "full_name": fields.get("full_name") or "Review required"})
    with engine.connect() as conn:
        possible = matches(conn, person)
    evidence = [e.model_dump() for e in parsed.evidence]
    mapped = {
        "industry": (fields.get("primary_domain"), "Industry / Domain"),
        "employer": (fields.get("current_employer"), "Current / last employer"),
        "employment": (history, "Employment history"),
        "employment_history": (history, "Employment history"),
        "institution": (extra.get("education_history"), "Education history"),
        "education_year": (extra.get("education_history"), "Education history"),
    }
    for item in evidence:
        value, destination = mapped.get(item["field"], (None, None))
        if value:
            item["saved_to_profile"] = True
            item["note"] = (
                f"Available in the editable {destination} fields. Only reviewed values are saved."
            )
    return {
        "candidate": fields,
        "extra": extra,
        "possible_matches": possible,
        "source_digest": hashlib.sha256(raw.encode()).hexdigest(),
        "evidence": evidence,
        "warnings": parsed.missing,
        "employment_suggestions": [e.model_dump() for e in parsed.employment_history],
        "unmapped": unmapped,
        "raw_text_persisted": False,
        "review_required": True,
    }

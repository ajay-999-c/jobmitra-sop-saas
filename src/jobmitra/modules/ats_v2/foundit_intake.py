"""Native V12 adaptation of the existing deterministic Foundit parser. No network or writes."""

import hashlib
import re

from pydantic import Field

from jobmitra.modules.candidates.foundit import parse_foundit_text

from .candidate_profiles import CompleteCreate, Strict, matches


class Paste(Strict):
    raw: str = Field(min_length=1, max_length=50000)


def preview(engine, raw):
    text = re.sub(r"(?im)^\s*Current\s+Company\s*:", "Company:", raw)
    text = re.sub(r"(?im)^\s*Current\s+Designation\s*:", "Designation:", text)
    special = {}
    lines = []
    for line in text.splitlines():
        match = re.match(
            r"\s*(Expected\s+(?:CTC|salary)|(?:Professional\s+)?Summary)\s*:\s*(.*)", line, re.I
        )
        if match:
            special[match[1].lower()] = match[2]
        else:
            lines.append(line)
    parsed = parse_foundit_text("\n".join(lines))
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
    extra = {
        k: old[k]
        for k in ["notice_period_text", "experience_months", "ready_to_relocate"]
        if k in old
    }
    if "experience_months" in extra:
        fields["experience_years"] = extra["experience_months"] / 12
    for label, value in special.items():
        if "summary" in label:
            fields["professional_summary"] = value
        else:
            salary = parse_foundit_text("Current CTC: " + value).fields
            if salary.current_salary_amount is not None:
                fields["expected_salary_inr"] = str(salary.current_salary_amount)
            period = {"Monthly": "MONTHLY", "Annual": "ANNUAL"}.get(salary.current_salary_period)
            if period:
                fields["expected_salary_period"] = period
    # Identity checks use normalized phone/email only; a name match alone is not a duplicate.
    person = CompleteCreate(**{**fields, "full_name": fields.get("full_name") or "Review required"})
    with engine.connect() as conn:
        possible = matches(conn, person)
    return {
        "candidate": fields,
        "extra": extra,
        "possible_matches": possible,
        "source_digest": hashlib.sha256(raw.encode()).hexdigest(),
        "evidence": [e.model_dump() for e in parsed.evidence],
        "warnings": parsed.missing,
        "employment_suggestions": [e.model_dump() for e in parsed.employment_history],
        "raw_text_persisted": False,
        "review_required": True,
    }

"""Deterministic, in-memory Foundit preview. No persistence, inference of consent or AI."""

import re
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import Field, ValidationError

from jobmitra.core.validation import InputModel, Positive, skills

from .schemas import CandidateFields, CandidateProfile, mobile_key


class FounditPaste(InputModel):
    raw: str = Field(min_length=1, max_length=50000)


class FieldEvidence(InputModel):
    field: str
    raw: str
    note: str
    needs_confirmation: bool = True
    saved_to_profile: bool = True


class EmploymentPreview(InputModel):
    kind: str
    role: str = ""
    employer: str = ""
    start: str = ""
    end: str = ""
    industry: str = ""
    raw: str
    warning: str = "Review role/employer boundaries before accepting."


class FounditCandidatePreview(InputModel):
    fields: CandidateFields
    evidence: list[FieldEvidence]
    missing: list[str]
    preview_only: dict[str, str]
    employment_history: list[EmploymentPreview] = Field(default_factory=list)
    state: Literal["Needs confirmation"] = "Needs confirmation"


class FounditCreate(CandidateProfile):
    source: Literal["Foundit"] = "Foundit"
    confirmed: Literal[True]
    recorded_by_staff_id: UUID


class FounditPatch(CandidateFields):
    version: Positive
    confirmed: Literal[True]
    recorded_by_staff_id: UUID
    # This intake cannot manufacture a walk-in, visit or search request.
    source: Literal["Foundit"] | None = None


LABELS = {
    "full_name": r"(?:full\s+name|candidate\s+name|name)",
    "mobile": r"(?:mobile\s*(?:no\.?|number)?|phone(?:\s+number)?)",
    "email": r"e-?mail",
    "experience_months": r"(?:total\s+)?experience",
    "current_salary_amount": r"(?:current\s+)?(?:salary|ctc)",
    "notice_period_text": r"(?:notice\s*(?:period)?|availability)",
    "current_location": r"(?:current\s+(?:city|location)|city|location)",
    "past_employment": r"(?:past|previous)(?:\s+employment)?",
    "past_industry": r"past\s+industry",
    "ready_to_relocate": r"(?:ready\s+to\s+relocate|relocation)",
    "institution": r"(?:university|institution)",
    "education_year": r"(?:education\s+year|graduation\s+year)",
    "employment": r"(?:current\s+employment|employment|current)",
    "skills": r"(?:key\s+)?skills",
    "preferred_locations": r"(?:pref\.?|preferred)\s*locations?",
    "qualification": r"(?:education|qualification)",
    "industry": r"current\s+industry|industry",
    "role_title": r"(?:job\s+role|designation|role|current\s+title)",
    "employer": r"(?:employer|company)",
}
LABEL_PATTERN = re.compile(
    r"(?<!\w)(?:"
    + "|".join(f"(?P<{key}>{value})" for key, value in LABELS.items())
    + r")\s*[:：]\s*",
    re.I,
)
PLACEHOLDER = re.compile(
    r"^(?:name|full name|candidate name|mobile(?:\s*no)?|phone|email|e-mail|"
    r"n/?a|not available)[.\s]*$",
    re.I,
)


def clean(value):
    return " ".join(value.split()).strip(" •\t")


CONTACT_EMAIL = re.compile(r"[^\s,:;]+@[^\s,:;]+")
CONTACT_PHONE = re.compile(r"(?<![\w])(?:\+?91[ -]*)?[6-9](?:[ -]*\d){7,11}(?![\w])")


def indian_mobile(value):
    digits = re.sub(r"\D", "", value)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return bool(re.fullmatch(r"[6-9]\d{9}", digits))


def parse_foundit_text(raw: str) -> FounditCandidatePreview:
    raw = FounditPaste(raw=raw).raw
    text = re.sub(r"(?m)^\s*[•●▪*\-]\s*", "", raw.replace("\r\n", "\n"))
    # Remove standalone placeholder/footer lines, not genuine skill spellings.
    text = "\n".join(
        line
        for line in text.splitlines()
        if not PLACEHOLDER.fullmatch(line.strip())
        and line.strip().casefold() not in {"linkedin", "newly added", "all skills"}
    )
    matches = list(LABEL_PATTERN.finditer(text))
    chunks: dict[str, list[str]] = {}
    for i, match in enumerate(matches):
        value = text[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)
        ].strip()
        if match.lastgroup not in {"mobile", "email"}:
            contact = [
                m.start()
                for pattern in (CONTACT_EMAIL, CONTACT_PHONE)
                for m in pattern.finditer(value)
            ]
            if contact:
                value = value[: min(contact)].strip()
        if value and not PLACEHOLDER.fullmatch(value):
            chunks.setdefault(match.lastgroup, []).append(value)
    prefix = text[: matches[0].start()] if matches else text
    lines = [clean(line) for line in prefix.splitlines() if clean(line)]
    values: dict = {"source": "Foundit"}
    evidence: list[FieldEvidence] = []
    preview_only = {"collection_method": "WhatsApp manual paste"}

    def note(
        field, source, message="Extracted from pasted text; confirm before saving.", saved=True
    ):
        evidence.append(
            FieldEvidence(field=field, raw=source, note=message, saved_to_profile=saved)
        )

    def single(field):
        entries = list(dict.fromkeys(clean(v) for v in chunks.get(field, [])))
        if len(entries) > 1:
            note(
                field,
                " | ".join(entries),
                "Conflicting repeated values. Enter the confirmed value.",
            )
            return None
        return entries[0] if entries else None

    for field in (
        "full_name",
        "mobile",
        "email",
        "current_location",
        "notice_period_text",
        "qualification",
        "role_title",
    ):
        entry = single(field)
        if not entry:
            continue
        if field in {"mobile", "email"}:
            entry = entry.strip().rstrip(".")
        if field == "email":
            entry = entry.casefold()
        if field == "current_location":
            entry = entry.rstrip(".")
        try:
            if field == "mobile" and not indian_mobile(entry):
                raise ValueError("Incomplete Indian mobile")
            CandidateFields.model_validate({field: entry})
            values[field] = entry
            note(field, entry)
        except (ValidationError, ValueError):
            note(
                field,
                entry,
                "Invalid format. Enter a confirmed value; this value will not be saved.",
            )

    # Unlabelled contact tokens are suggestions only, never confirmed automatically.
    for field, pattern in (
        ("email", CONTACT_EMAIL),
        ("mobile", CONTACT_PHONE),
    ):
        candidates = []
        for match in re.finditer(pattern, text):
            entry = match.group().strip().rstrip(".")
            try:
                if field == "mobile" and not indian_mobile(entry):
                    note(
                        field,
                        entry,
                        "Incomplete or invalid Indian mobile. Confirm without guessing digits.",
                    )
                    continue
                CandidateFields.model_validate({field: entry})
            except ValidationError:
                continue
            candidates.append(entry.casefold() if field == "email" else entry)
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) == 1:
            values[field] = candidates[0]
            note(field, candidates[0], "Unlabelled contact; verify it belongs to this person.")
        elif candidates:
            values.pop(field, None)
            note(
                field,
                " | ".join(candidates),
                "Multiple contacts found. Choose the confirmed contact.",
            )

    if "full_name" not in chunks and lines:
        first = lines[0]
        if re.fullmatch(r"[^\W\d_][^\d@₹:]{1,99}", first) and not re.search(
            r"joiner|skills|lac|lakh|lpa", first, re.I
        ):
            values["full_name"] = first
            note("full_name", first, "Possible name from the first line; confirm identity.")

    exp = single("experience_months")
    if exp is None and "experience_months" not in chunks:
        exp = next(
            (line for line in lines if re.search(r"\d\s*(?:y|year|m|month)", line, re.I)), None
        )
    if exp:
        match = re.fullmatch(
            r"\s*(?:(\d+)\s*(?:y(?:ears?)?|yrs?)\s*)?(?:(\d+)\s*(?:m(?:onths?)?|mos?)\s*)?",
            exp,
            re.I,
        )
        if match and any(match.groups()) and (not match[1] or not match[2] or int(match[2]) < 12):
            values["experience_months"] = int(match[1] or 0) * 12 + int(match[2] or 0)
            note("experience_months", exp)
        else:
            note("experience_months", exp, "Ambiguous experience. Enter total months after review.")

    salary = single("current_salary_amount")
    if salary is None and "current_salary_amount" not in chunks:
        salary = next(
            (line for line in lines if re.search(r"₹|\b(?:INR|lac|lakh|lpa)\b", line, re.I)), None
        )
    if salary:
        values["last_salary_raw"] = salary
        pattern = (
            r"(?:₹|INR|Rs\.?)?\s*([\d,]+(?:\.\d+)?)\s*(lac|lakh|lakhs|lacs|lpa|k)?"
            r"\s*(?:(?:per\s+|/\s*)?(month|monthly|annum|annual|year|yearly))?"
        )
        match = re.fullmatch(pattern, salary, re.I)
        if (
            match
            and "," in match[1]
            and not re.fullmatch(
                r"(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d+)?", match[1]
            )
        ):
            match = None
        if match:
            try:
                amount = Decimal(match[1].replace(",", ""))
                unit = (match[2] or "").casefold()
                amount *= (
                    100000 if unit.startswith("la") or unit == "lpa" else 1000 if unit == "k" else 1
                )
                CandidateFields(current_salary_amount=amount)
                values["current_salary_amount"] = amount
                period = (match[3] or "").casefold()
                values["current_salary_period"] = (
                    "Annual"
                    if unit == "lpa" or period in {"annual", "annum", "year", "yearly"}
                    else "Monthly"
                    if period in {"monthly", "month"}
                    else "Unknown"
                )
                note(
                    "current_salary_amount",
                    salary,
                    "INR amount. Period remains Unknown unless explicitly stated; confirm units.",
                )
            except (InvalidOperation, ValidationError):
                note(
                    "current_salary_amount",
                    salary,
                    "Salary is outside supported precision; confirm manually.",
                )
        else:
            note("current_salary_amount", salary, "Ambiguous salary or units. No amount inferred.")

    for i, line in enumerate(lines):
        if re.fullmatch(r"Immediate\s+Joiner", line, re.I):
            if "notice_period_text" not in chunks:
                values["notice_period_text"] = "Immediate Joiner"
                note(
                    "notice_period_text",
                    line,
                    "Availability only; no joining date or consent inferred.",
                )
            if (
                "current_location" not in chunks
                and i + 1 < len(lines)
                and re.fullmatch(r"[A-Za-z .'-]+", lines[i + 1])
            ):
                values["current_location"] = lines[i + 1].rstrip(".")
                note(
                    "current_location",
                    lines[i + 1],
                    "Possible city following availability; confirm context.",
                )

    for field in ("skills", "preferred_locations"):
        entries = chunks.get(field, [])
        if entries:
            parts = []
            for entry in entries:
                entry = (
                    re.sub(r"(?:All\s+skills\s*)+$", "", entry, flags=re.I)
                    if field == "skills"
                    else entry.rstrip(".")
                )
                parts.extend(part for part in re.split(r"[,;\n]", entry) if part.strip())
            values[field] = skills(parts)
            note(
                field,
                "\n".join(entries),
                "Duplicates and UI footer removed; original skill spellings retained.",
            )

    for field in ("industry", "employer", "employment"):
        entry = single(field)
        if not entry:
            continue
        preview_only[field] = entry
        note(field, entry, "Preview only: no matching candidate column. Not saved.", False)
        if field == "employment":
            date_match = re.search(
                r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\s+to\s+.+",
                entry,
                re.I,
            )
            title_employer = entry[: date_match.start()].strip() if date_match else entry
            if date_match:
                preview_only["employment_dates"] = date_match.group()
            split = re.split(r"(?<=[a-z])(?=[A-Z])|\s+at\s+|\s+@\s+", title_employer, maxsplit=1)
            if len(split) == 2:
                if "role_title" not in values:
                    values["role_title"] = split[0].strip()
                    note(
                        "role_title",
                        entry,
                        "Possible role/employer boundary. Review required; "
                        "do not accept without checking.",
                    )
                preview_only["employer_suggestion"] = split[1].strip()
            else:
                note(
                    "role_title",
                    entry,
                    "Role/employer boundary unclear. Enter the confirmed role manually.",
                )

    history = []
    date_pattern = re.compile(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})"
        r"\s+to\s+(Present|Current|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})"
        r"(?:\s*-\s*\d+\s*y(?:\s+\d+\s*m)?|\s*-\s*\d+\s*m)?",
        re.I,
    )
    for kind, key, industry_key in (
        ("Current", "employment", "industry"),
        ("Past", "past_employment", "past_industry"),
    ):
        for entry in chunks.get(key, []):
            cursor = 0
            records = []
            for match in date_pattern.finditer(entry):
                records.append(
                    (
                        entry[cursor : match.start()].strip(),
                        match[1],
                        match[2],
                        entry[cursor : match.end()].strip(),
                    )
                )
                cursor = match.end()
            if entry[cursor:].strip():
                records.append((entry[cursor:].strip(), "", "", entry[cursor:].strip()))
            for title, start, end, original in records:
                split = re.split(r"(?<=[a-z])(?=[A-Z])|\s+at\s+|\s+@\s+", title, maxsplit=1)
                history.append(
                    EmploymentPreview(
                        kind=kind,
                        role=split[0] if len(split) == 2 else "",
                        employer=split[1] if len(split) == 2 else "",
                        start=start,
                        end=end,
                        industry=single(industry_key) or "",
                        raw=original,
                    )
                )
    for key in ("past_industry", "institution", "education_year"):
        if single(key):
            preview_only[key] = single(key)
    if not any(item.kind == "Current" for item in history) and preview_only.get("employer"):
        history.insert(
            0,
            EmploymentPreview(
                kind="Current",
                employer=preview_only["employer"],
                role=values.get("role_title", ""),
                industry=preview_only.get("industry", ""),
                raw=preview_only["employer"],
                warning="Confirm the supplied employer and role.",
            ),
        )
    education = values.get("qualification", "")
    # Comma-separated education is a suggestion only; retain its full original wording.
    education_parts = [part.strip() for part in education.split(",")]
    if len(education_parts) >= 3 and re.fullmatch(r"(?:19|20)\d{2}", education_parts[-1]):
        preview_only.setdefault("education_year", education_parts[-1])
        preview_only.setdefault("institution", education_parts[-2])
        note(
            "qualification",
            education,
            "Possible institution/year split; review the additional details.",
        )
    relocation = single("ready_to_relocate")
    if relocation:
        if relocation.casefold() in {"yes", "no", "true", "false"}:
            values["ready_to_relocate"] = relocation.casefold() in {"yes", "true"}
        else:
            note(
                "ready_to_relocate",
                relocation,
                "Unclear relocation preference; confirm explicitly.",
            )

    # Placeholders must never become candidate identities, even via labelled input.
    for field in ("full_name", "mobile", "email"):
        if values.get(field) and PLACEHOLDER.fullmatch(str(values[field])):
            values.pop(field)
    return FounditCandidatePreview(
        fields=CandidateFields.model_validate(values),
        evidence=evidence,
        missing=[field for field in ("full_name", "mobile") if not values.get(field)],
        preview_only=preview_only,
        employment_history=history,
    )


def confirmed_identity(data):
    """Reject common copy/paste placeholders at the persistence boundary too."""
    for field in ("full_name", "mobile", "email"):
        value = getattr(data, field, None)
        if value and PLACEHOLDER.fullmatch(value):
            raise ValueError(f"Confirm {field}; placeholder text is not a value")
    if getattr(data, "mobile", None):
        mobile_key(data.mobile)
        if not indian_mobile(data.mobile):
            raise ValueError("Confirm a valid 10-digit Indian mobile, optionally prefixed with +91")

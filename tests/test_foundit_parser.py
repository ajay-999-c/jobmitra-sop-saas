from decimal import Decimal

import pytest
from pydantic import ValidationError

from jobmitra.modules.candidates.foundit import (
    FounditCandidatePreview,
    FounditPaste,
    parse_foundit_text,
)

SAMPLE = """name
5y 3m
₹ 2 Lac
Immediate Joiner
Indore
Current:
Field Sales ExecutiveAditya Birla Fashion and RetailOct 2025 to Present - 1y
Skills:
Basic Computer Fandamentals, Tally, Tallyerp9, Html, Css, Javascript, \
Bootstrap, React.js, ProgrammingAll skills
Pref. location:
Indore.
Education:
Bachelor Of Technology (B.Tech/B.E)- Computers, DAVV University, 2024
Current industry:
Fashion
mobileno.
email."""


def test_exact_reference_sample_is_uncertain_and_typed():
    result = parse_foundit_text(SAMPLE)
    assert isinstance(result, FounditCandidatePreview)
    fields = result.fields
    assert fields.experience_months == 63
    assert fields.current_salary_amount == Decimal("200000")
    assert fields.current_salary_period == "Unknown"
    assert fields.notice_period_text == "Immediate Joiner"
    assert fields.current_location == "Indore"
    assert fields.preferred_locations == ["Indore"]
    assert fields.full_name is fields.mobile is fields.email is None
    assert result.missing == ["full_name", "mobile"]
    assert fields.domain_id is fields.subdomain_id is None
    assert fields.skills[0] == "Basic Computer Fandamentals"
    assert fields.skills[-1] == "Programming"
    assert result.preview_only["industry"] == "Fashion"
    assert "ExecutiveAditya" in result.preview_only["employment"]
    assert result.preview_only["employer_suggestion"] == "Aditya Birla Fashion and Retail"
    assert fields.role_title == "Field Sales Executive"
    assert all(item.needs_confirmation for item in result.evidence)


def test_labels_case_whitespace_and_repeated_skills():
    result = parse_foundit_text("""• NAME:
  Anita   Sharma
• MOBILE: +91 98765 43210
• EMAIL: ANITA@EXAMPLE.COM
EXPERIENCE: 5 years 3 months
Salary: INR 2 LPA
Skills: Tally, tally, Excel
SQL
Skills: Excel, SQL All skills All skills
Current city: Indore.
""")
    assert result.fields.full_name == "Anita Sharma"
    assert result.fields.email == "anita@example.com"
    assert result.fields.experience_months == 63
    assert result.fields.current_salary_period == "Annual"
    assert result.fields.skills == ["Tally", "Excel", "SQL"]


def test_run_together_labels_and_clear_employment():
    result = parse_foundit_text(
        "Name: Anita Sharma Mobile: 9876543210 Email: anita@example.com "
        "Experience: 5y 3m Salary: 25000 Monthly Current: Analyst at Example Ltd "
        "Skills: Excel, SQL Current industry: Retail"
    )
    assert result.fields.full_name == "Anita Sharma"
    assert result.fields.mobile == "9876543210"
    assert result.fields.current_salary_amount == Decimal("25000")
    assert result.fields.current_salary_period == "Monthly"
    assert result.fields.role_title == "Analyst"
    assert result.preview_only["employer_suggestion"] == "Example Ltd"


@pytest.mark.parametrize(
    "raw,field",
    [
        ("Experience: 5y 19m", "experience_months"),
        ("Experience: several years", "experience_months"),
        ("Salary: 2 to 3 lac", "current_salary_amount"),
        ("Salary: USD 2000", "current_salary_amount"),
        ("Email: broken@", "email"),
        ("Mobile: mobileno.", "mobile"),
        ("Name: name", "full_name"),
        ("Mobile: 9876543210 Mobile: 8765432109", "mobile"),
    ],
)
def test_invalid_or_conflicting_values_never_become_facts(raw, field):
    result = parse_foundit_text(raw)
    assert getattr(result.fields, field) is None
    assert result.state == "Needs confirmation"


def test_raw_size_is_bounded():
    with pytest.raises(ValidationError):
        FounditPaste(raw="x" * 50001)


def test_only_trailing_footer_removed_and_bad_grouping_flagged():
    parsed = parse_foundit_text("Skills: All skills Training, ProgrammingAll skills All skills")
    assert parsed.fields.skills == ["All skills Training", "Programming"]
    bad = parse_foundit_text("Salary: ₹ 2,3 Lac")
    assert bad.fields.current_salary_amount is None
    assert any("Ambiguous salary" in item.note for item in bad.evidence)


@pytest.mark.parametrize(
    "wording,months", [("5y 3m", 63), ("2y 7m", 31), ("4y 2m", 50), ("6y", 72), ("8m", 8)]
)
def test_explicit_total_not_employment_duration(wording, months):
    result = parse_foundit_text(
        f"Total experience: {wording}\nCurrent: AnalystExample LtdOct 2025 to Present - 1y"
    )
    assert result.fields.experience_months == months


@pytest.mark.parametrize(
    "role,employer,experience,months",
    [
        ("Field Sales Executive", "Aditya Birla Fashion and Retail", "5y 3m", 63),
        ("Internal Auditor", "Assure Insight Consulting Pvt. Ltd.", "2y 7m", 31),
        ("Senior Escalation Officer", "Example Support Ltd", "4y 2m", 50),
    ],
)
def test_synthetic_footer_contacts_and_multiple_jobs(role, employer, experience, months):
    result = parse_foundit_text(f"""Synthetic Person
Total experience: {experience}
Salary: ₹ 2 Lac
Current: {role}{employer}Oct 2025 to Present - 1y
Past: Sales AssistantShivprabha Pvt. Ltd.Jul 2024 to Dec 2024
AnalystExample ConsultingJan 2023 to Jun 2024
Skills: Excel, excel, All skills Training, SQL
LinkedIn
Newly added
All skills
Preferred locations: Indore, Pune
Current industry: Retail
Past industry: Consulting
+91 98765-43210
synthetic@example.com""")
    assert result.fields.mobile == "+91 98765-43210"
    assert result.fields.email == "synthetic@example.com"
    assert result.fields.experience_months == months
    assert result.fields.current_salary_period == "Unknown"
    assert result.fields.skills == ["Excel", "All skills Training", "SQL"]
    assert result.fields.preferred_locations == ["Indore", "Pune"]
    assert result.preview_only["past_industry"] == "Consulting"
    assert result.preview_only["industry"] == "Retail"
    assert len(result.employment_history) == 3
    current, past, older = result.employment_history
    assert current.role == role and current.employer == employer
    assert past.role == "Sales Assistant" and past.start == "Jul 2024" and past.end == "Dec 2024"
    assert older.employer == "Example Consulting"
    assert all(
        "@" not in item.raw and "98765" not in item.raw for item in result.employment_history
    )


def test_incomplete_contact_preserved_as_warning_without_guessing():
    result = parse_foundit_text("Current industry: Retail\n987654321\nperson@example.com")
    assert result.fields.mobile is None
    assert result.preview_only["industry"] == "Retail"
    assert any(e.raw == "987654321" and "Incomplete" in e.note for e in result.evidence)


def test_labelled_contact_does_not_swallow_unlabelled_footer_contact():
    result = parse_foundit_text(
        "Current industry: Retail\nEmail: Mixed@Example.com\n+91 98765 43210"
    )
    assert result.fields.email == "mixed@example.com"
    assert result.fields.mobile == "+91 98765 43210"
    assert result.preview_only["industry"] == "Retail"


QUICK_ENTRY_SAMPLE = (
    "Synthetic Parser Candidate\n"
    "LinkedIn\n"
    "Enriched\n"
    "2y 4m\n"
    "₹ 3.5 Lac\n"
    "Indore\n"
    "Current:\n"
    "lean engineerexample consultingJan 2023 to Jun 2023 - 5m\n"
    "Past:\n"
    "steering committee memberexample teamSep 2019 to Aug 2021\n"
    "Skills:\n"
    "Mechanical Maintenance /Quality Engineer, Mechanical Engineer, Design EngineerAll skills\n"
    "Pref. location:\n"
    "India, Indore, Pune, Delhi, Noida.\n"
    "Education:\n"
    "Bachelor Of Technology (B.Tech/B.E)- Mechanical, "
    "Example Institute of Technology, Indore, 2023\n"
    "Current industry:\n"
    "Others\n"
    "Past industry:\n"
    "Others\n"
    "+91-9000000001\n"
    "candidate@example.com\n"
)


def test_quick_entry_exact_sample_and_ended_current_job():
    result = parse_foundit_text(QUICK_ENTRY_SAMPLE)
    assert result.fields.full_name == "Synthetic Parser Candidate"
    assert result.fields.mobile == "+91-9000000001"
    assert result.fields.email == "candidate@example.com"
    assert result.fields.experience_months == 28
    assert result.fields.current_salary_amount == Decimal("350000")
    assert result.fields.current_salary_period == "Unknown"
    assert result.fields.current_location == "Indore"
    assert result.fields.domain_id is result.fields.subdomain_id is None
    assert result.fields.role_title is None  # lower-case glued words have no safe boundary
    assert result.fields.preferred_locations == ["India", "Indore", "Pune", "Delhi", "Noida"]
    assert result.fields.skills[-1] == "Design Engineer"
    current, past = result.employment_history
    assert current.end == "Jun 2023"
    assert "Employment status is uncertain" in current.warning
    assert current.employer == "" and current.role == ""
    assert past.end == "Aug 2021"
    assert (
        result.preview_only["institution"]
        == "Example Institute of Technology, Indore"
    )
    assert result.preview_only["education_year"] == "2023"

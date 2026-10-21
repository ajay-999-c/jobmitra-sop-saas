"""Prepare reviewed-workbook input only. Never connects to PostgreSQL or edits Excel."""

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobmitra.modules.companies.normalization import company_name_key  # noqa: E402


def distinct(values):
    return list(dict.fromkeys(v for v in values if v is not None and str(v).strip()))


def prepare(source: Path) -> dict:
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=False)
    try:
        sheet = workbook["Sheet1"]
        values = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    assert values[0] == (
        "Register ID",
        "Company / client (as read)",
        "Contact person(s) (as read)",
        "Phone 1 - readable digits",
        "Phone 2 - readable digits",
    )
    rows = [
        {
            "row": i,
            "id": v[0],
            "name": v[1],
            "contact": v[2],
            "phones": distinct(v[3:5]),
            "original": list(v),
        }
        for i, v in enumerate(values[1:], 2)
        if any(v)
    ]
    assert len({r["id"] for r in rows}) == len(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[company_name_key(row["name"])].append(row)
    reviews, review_keys = [], set()

    def flag(kind, keys, references, reason):
        review_keys.update(keys)
        reviews.append([kind, "; ".join(keys), "; ".join(map(str, references)), reason, None, None])

    for key, group in groups.items():
        if len(group) > 1:
            payloads = {
                (
                    company_name_key(r["name"]),
                    company_name_key(r["contact"]) if r["contact"] else None,
                    tuple(r["phones"]),
                )
                for r in group
            }
            if len(payloads) > 1:
                flag(
                    "Merge review",
                    [key],
                    [r["row"] for r in group],
                    "Same normalized company name, different contact/phone details. "
                    "Provisional union only; verify company identity before any import.",
                )
    keys = list(groups)
    for pos, key in enumerate(keys):
        for other in keys[pos + 1 :]:
            a, b = [re.sub(r"[^\w]", "", k) for k in (key, other)]
            if SequenceMatcher(None, a, b).ratio() >= 0.82:
                flag(
                    "Similar names",
                    [key, other],
                    [r["row"] for k in (key, other) for r in groups[k]],
                    "Similar spelling only. Kept separate; do not merge without review.",
                )
    phones = defaultdict(list)
    for row in rows:
        key = company_name_key(row["name"])
        for phone in row["phones"]:
            phones[phone].append((key, row["row"]))
        if row["contact"] and re.search(r"[/&;]", row["contact"]):
            flag(
                "Contact split",
                [key],
                [row["row"]],
                "Source contact text has a delimiter. Preserved unsplit; verify people/roles.",
            )
    for occurrences in phones.values():
        involved = distinct(k for k, _ in occurrences)
        if len(involved) > 1:
            flag(
                "Shared phone",
                involved,
                distinct(r for _, r in occurrences),
                "A phone appears under different company names. Kept at both; verify identity.",
            )

    companies, contacts = [], []
    for key, group in groups.items():
        ids = [r["id"] for r in group]
        numbers = distinct(p for r in group for p in r["phones"])
        status = (
            "MANUAL REVIEW"
            if key in review_keys
            else "Consolidated"
            if len(group) > 1
            else "Single entry"
        )
        companies.append(
            [
                group[0]["name"],
                key,
                json.dumps(ids),
                json.dumps(numbers),
                None,
                None,
                None,
                None,
                status,
                "; ".join(map(str, [r["row"] for r in group])),
                "; ".join(distinct(r["name"] for r in group)),
            ]
        )
        # No unsupported phone-to-person assignment or splitting of source names.
        names = defaultdict(list)
        for row in group:
            if row["contact"]:
                names[row["contact"].strip()].append(row)
        for name, contact_rows in names.items():
            contacts.append(
                [
                    key,
                    name,
                    None,
                    "[]",
                    json.dumps([r["id"] for r in contact_rows]),
                    "; ".join(str(r["row"]) for r in contact_rows),
                    "UNSPLIT: REVIEW" if re.search(r"[/&;]", name) else "Source text preserved",
                ]
            )
    assert len(companies) == len(groups)
    retained = [rid for row in companies for rid in json.loads(row[2])]
    assert sorted(retained) == sorted(r["id"] for r in rows)
    original_phones = {(company_name_key(r["name"]), p) for r in rows for p in r["phones"]}
    assert original_phones == {(r[1], p) for r in companies for p in json.loads(r[3])}
    assert {(company_name_key(r["name"]), r["contact"].strip()) for r in rows if r["contact"]} == {
        (r[0], r[1]) for r in contacts
    }
    assert all(r[4:8] == [None] * 4 for r in companies)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    return {
        "source_sha256": before,
        "summary": {
            "source_rows": len(rows),
            "companies": len(companies),
            "contact_text_records": len(contacts),
            "duplicate_name_groups": sum(len(g) > 1 for g in groups.values()),
            "manual_review_companies": len(review_keys),
            "review_items": len(reviews),
            "reviews_by_kind": {
                k: sum(r[0] == k for r in reviews) for k in sorted({r[0] for r in reviews})
            },
        },
        "sheets": [
            {
                "name": "Companies",
                "title": "Companies — consolidated candidates",
                "note": (
                    "Review flagged records before import. Arrays are JSON text. "
                    "Addresses stay blank. Source: company-dataset.xlsx / Sheet1."
                ),
                "headers": [
                    "Company name",
                    "Company name key",
                    "Source Register IDs",
                    "General phone numbers",
                    "Address line",
                    "City",
                    "State",
                    "Postal code",
                    "Review status",
                    "Source Excel rows",
                    "Original name spellings",
                ],
                "rows": companies,
                "widths": [34, 34, 27, 34, 28, 18, 18, 16, 22, 20, 38],
            },
            {
                "name": "Contacts",
                "title": "Contacts — preserved source text",
                "note": (
                    "Phone ownership is unverified: all source phones remain company-level. "
                    "Names with delimiters remain unsplit. Source: Sheet1 column C."
                ),
                "headers": [
                    "Company name key",
                    "Contact name / source text",
                    "Designation",
                    "Phone numbers",
                    "Source Register IDs",
                    "Source Excel rows",
                    "Review status",
                ],
                "rows": contacts,
                "widths": [34, 44, 22, 18, 27, 20, 26],
            },
            {
                "name": "Review",
                "title": "Manual review queue",
                "note": (
                    "Decision and reviewer note are editable. No decisions are prefilled. "
                    "Consolidated candidates are not approved company identities."
                ),
                "headers": [
                    "Review type",
                    "Company name keys",
                    "Source Excel rows",
                    "Reason",
                    "Decision",
                    "Reviewer note",
                ],
                "rows": reviews,
                "widths": [20, 56, 24, 74, 24, 40],
            },
            {
                "name": "Source Rows",
                "title": "Original row references",
                "note": (
                    "Unmodified values copied for traceability. Excel row numbers refer to "
                    "the original Sheet1. No source values are inferred."
                ),
                "headers": ["Original Excel row", *values[0]],
                "rows": [[r["row"], *r["original"]] for r in rows],
                "widths": [21, 18, 38, 44, 29, 29],
            },
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    data = prepare(ROOT / "company-dataset.xlsx")
    args.output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    args.output_json.chmod(0o600)
    print(json.dumps(data["summary"]))

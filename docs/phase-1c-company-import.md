# Phase 1C — Company import

Completed on 2026-10-15 against local PostgreSQL 18, database `jobmitra_dev`,
schema `public`, Alembic revision `0001_company_management`. No migration or
schema changes were made. The pgvector extension remains unchanged and unused.

## Source reconciliation

The read-only input is `outputs/phase-1a/company-dataset-cleaned.xlsx`. Its four
sheets use headers on row 6 and data from row 7:

| Sheet | Records | Purpose |
| --- | ---: | --- |
| Companies | 166 | Consolidated company candidates, source IDs and general phones |
| Contacts | 159 | Original contact text associated with each company candidate |
| Review | 37 | Unresolved merge, similar-name, shared-phone and contact-split issues |
| Source Rows | 180 | Original entries, with original Excel row and Register ID |

Every Source Rows record matches `company-dataset.xlsx` exactly. All 180 Register
IDs are distinct, occur exactly once across the 166 company candidates and map
to the correct original rows. Consolidation reduces the candidate count by 14.
Company keys use the existing NFKC/whitespace/casefold normalization; punctuation
and suffixes are retained. Every company-level phone array exactly preserves the
distinct source digit strings, including leading zeros.

All 37 review decisions and reviewer notes are blank. Independent checks recompute
conflicting duplicate payloads, similar-name pairs and shared phones from the
original rows, so removing review flags cannot approve an uncertain identity.
These checks withhold 32 companies. Three additional unclear company labels bring
the total withheld to 35; two other unclear labels were already identity-blocked.
Similar spelling or a shared phone is treated as a review signal, not proof of a
duplicate. Companies with only ambiguous contact text remain eligible themselves.

## Applied results

| Outcome | Count |
| --- | ---: |
| Companies inserted | 131 |
| Contacts inserted | 108 |
| Original Register IDs preserved in inserted companies | 134 |
| Distinct company-scoped general phone values preserved | 81 |
| Companies withheld for review | 35 |
| Original Register IDs retained with withheld candidates | 46 |
| Contact candidates skipped because their company was withheld | 42 |
| Ambiguous/unclear contact candidates skipped under accepted companies | 9 |

The 159 contact candidates reconcile as 108 inserted + 42 withheld with their
parent + 9 ambiguous or unclear. Split names, unclear labels and role-only labels
are not guessed into individual contact records. All original text remains in the
unchanged Contacts, Review and Source Rows sheets. The JSON reports identify
additional quarantined text by Excel row reference; no workbook was rewritten.

Every inserted company has NULL `address_line`, `city`, `state` and `postal_code`.
Every inserted contact has NULL designation and an empty phone array. No general
phone was assigned to a contact. The phone count above is deduplicated within each
company; it is not a claim that a phone identifies a person.

Before import, both tables were empty. The first apply committed 131 companies and
108 contacts. A second actual apply returned 131 `already_present` and 35
`withheld_ambiguous_company`, with zero inserts. Hashes of every stored field,
UUID and timestamp were unchanged across the second apply. Schema columns,
constraints and indexes, extensions, revision and both source file hashes were
unchanged. Final counts: 131 companies, 108 contacts.

Evidence:

- [Read-only dry-run](../outputs/phase-1c/dry-run.json)
- [Applied import and per-company decisions](../outputs/phase-1c/apply.json)
- [Second apply](../outputs/phase-1c/idempotency-apply.json)
- [Post-import verification](../outputs/phase-1c/verification.json)

## Running the importer

From the project root:

```sh
uv sync --extra dev --extra import
.venv/bin/python scripts/import_companies.py --dry-run
.venv/bin/python scripts/import_companies.py --apply
```

The installed `jobmitra-import-companies` command accepts the same arguments.
`--source`, `--original` and `--report` override paths. The importer is deliberately
specific to this 166-candidate/180-entry dataset. It requires the original workbook
as corroborating evidence, the exact cleaned sheet/column structure, local
`jobmitra_dev`, PostgreSQL major version 18, public schema and the existing revision.
It rejects formulas, error cells, missing coverage, invented phone ownership,
incorrect source mappings and duplicate normalized keys before inserting anything.

Database settings come from the existing environment configuration. No password,
connection URL, raw driver exception, contact names or phone values are printed.
`openpyxl` is an optional `import` extra; normal backend startup does not load it.

Dry-run uses `SET TRANSACTION READ ONLY`, checks existing rows and writes only a
local JSON report. Apply uses a single SQLAlchemy transaction with rollback on
failure and a transaction-scoped advisory lock to serialize importer executions.
New companies and their accepted contacts are inserted together; sessions and
engines close on every exit. No DDL, UPDATE, DELETE or TRUNCATE is issued.

Source IDs identify already imported companies even after manual renaming. Partial
or conflicting source ownership is skipped. A matching normalized name without
those source IDs is reported as `existing_name_conflict`; the existing company is
not overwritten or given additional source IDs/contacts. Existing company and
contact records are never attached for updates. Repeating an import also does not
recreate a manually removed contact or supplement a previously imported company.
Concurrent UI writes that cause a uniqueness failure roll back the import batch.

Reports default to unique UTC filenames in `outputs/phase-1c`. An existing report
path is refused; reports are not overwritten. Reports are set to owner-only
permissions. Exit codes: 0 success, 1 validation/database failure, 2 report-write
failure after database work finished. If an apply commits but its report cannot be
written, output explicitly reports `committed_without_report`; rerunning remains
safe because the database checks establish identity again.

## Manual review and boundaries

Keep the source workbook unchanged. Review its existing tabs alongside the row
references below. A future reviewed copy can record `Merge confirmed` for a merge
issue, or `Keep separate` / `Verified source` for similar-name and shared-phone
issues, always with a reviewer note and matching original row references. Each
company must have all its identity issues resolved. Contact-split decisions alone
cannot create parsed contacts; unclear identities and ownership need a separately
reviewed correction rather than guessed values. This phase does not implement that
correction or backfill workflow.

## Focused validation

```sh
JOBMITRA_RUN_IMPORT_TESTS=1 .venv/bin/pytest -q tests/test_company_import.py
.venv/bin/ruff check src/jobmitra/modules/companies/importer.py scripts/import_companies.py tests/test_company_import.py
```

16 importer tests passed in 3.31 seconds: source reconciliation and corruption
rejection, contact ownership protection, review safeguards, dry-run, repeated
apply, preservation of manually edited records, name/source conflicts and a
simulated failure after INSERT proving batch rollback. Live cases use unique
synthetic records inside outer transactions that are always rolled back. Ruff
checks and formatting passed. No unrelated regression suite was run.

## Withheld company candidates

Excel row numbers below refer to the Companies sheet in the cleaned workbook.
Reason codes are those emitted by the importer; multiple signals can apply.

| Company | Register IDs | Excel row | Reasons |
| --- | --- | ---: | --- |
| [unclear] Bishemelue | REG-0115 | 115 | unclear_company_name |
| Akshat Agro milling Pvt. Ltd. | REG-0043, REG-0099 | 48 | unresolved_merge_review |
| Aman Enterprises | REG-0092 | 97 | unresolved_similar_names |
| Ashwin Stocks & Investment Pvt. Ltd. | REG-0158 | 154 | unresolved_similar_names |
| Ashwin Stocks / Investment | REG-0048 | 53 | unresolved_similar_names |
| Asian Enterprises | REG-0110, REG-0182 | 112 | unresolved_merge_review, unresolved_similar_names |
| Bajaj & Sons | REG-0049 | 54 | unresolved_shared_phone |
| Balaji Ply Decor | REG-0065, REG-0148 | 70 | unresolved_merge_review |
| Capital Transport | REG-0098 | 103 | unresolved_shared_phone, unresolved_similar_names |
| Capital Transport Pvt. Ltd. | REG-0093 | 98 | unresolved_shared_phone, unresolved_similar_names |
| Cycle World | REG-0019, REG-0033 | 25 | unresolved_merge_review |
| Dig Grains | REG-0024 | 30 | unresolved_shared_phone, unresolved_similar_names |
| DIGIGRAINS | REG-0109 | 111 | unresolved_shared_phone, unresolved_similar_names |
| E[unclear] group | REG-0108 | 110 | unclear_company_name |
| ES Infraserve | REG-0107 | 109 | unresolved_shared_phone |
| ES Infraserve pvt. ltd. | REG-0013 | 19 | unresolved_shared_phone |
| Glance Windoors | REG-0022, REG-0111 | 28 | unresolved_merge_review |
| Gupta Enterprises | REG-0112, REG-0113 | 113 | unresolved_merge_review, unresolved_shared_phone |
| Iconic Bituminous Pvt. Ltd. | REG-0036 | 41 | unresolved_shared_phone |
| Impact Infra Equipments Pvt. Ltd. | REG-0118 | 116 | unresolved_similar_names |
| Impat Infra Equipment Pvt. Ltd. | REG-0020 | 26 | unresolved_similar_names |
| Indira Securities | REG-0035, REG-0117 | 40 | unresolved_merge_review |
| Mantra Filter[unclear] Products | REG-0068 | 73 | unclear_company_name, unresolved_shared_phone |
| Mantra Filtration Products | REG-0071 | 76 | unresolved_shared_phone |
| Narmada Extrusions | REG-0074 | 79 | unresolved_similar_names |
| Narmada Extrusions Ltd. | REG-0021 | 27 | unresolved_similar_names |
| OM Shiv [unclear] | REG-0077 | 82 | unclear_company_name, unresolved_shared_phone |
| Raman Enterprises | REG-0076 | 81 | unresolved_similar_names |
| Sai baba Agri link | REG-0006 | 12 | unresolved_shared_phone, unresolved_similar_names |
| SAIBABA AGRI LINK PVT. LTD. | REG-0126 | 124 | unresolved_shared_phone, unresolved_similar_names |
| Sapcon Instruments | REG-0023, REG-0167 | 29 | unresolved_merge_review |
| Sharleen Overseas | REG-0127, REG-0165 | 125 | unresolved_merge_review |
| SM Agro Impex | REG-0122, REG-0164 | 120 | unresolved_merge_review |
| SND Construction | REG-0130, REG-0143 | 128 | unresolved_merge_review |
| Spay[unclear] | REG-0101 | 105 | unclear_company_name |

## Skipped contact text under imported companies

These references identify the nine contact candidates omitted under accepted
companies. Consult the unchanged Contacts sheet for the original text. Contacts
under withheld companies are separately listed in each JSON report's
`contact_review` array; all 51 skipped candidates remain traceable there.

| Companies row | Contacts row | Reasons |
| ---: | ---: | --- |
| 7 | 7 | unclear_contact_name |
| 32 | 33 | ambiguous_contact_split |
| 37 | 38 | ambiguous_contact_split |
| 117 | 113 | unclear_contact_name |
| 134 | 130 | ambiguous_contact_split |
| 141 | 137 | ambiguous_contact_split |
| 144 | 140 | ambiguous_contact_split |
| 158 | 154 | ambiguous_contact_split |
| 164 | 159 | ambiguous_contact_split |

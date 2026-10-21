# Phase 1A validation — 15 October 2026

## Applied schema

- Target: local macOS PostgreSQL 18.6, database `jobmitra_dev`.
- Applied revision: `0001_company_management`.
- Exactly two business tables: `companies` and `company_contacts`.
- Additional table: Alembic's standard `alembic_version` migration ledger.
- Both business tables contain zero rows. No workbook records imported.
- pgvector remains installed at 0.8.7. No vector columns, indexes or dependencies added.
- Preflight found no existing application tables. Post-application catalog comparisons
  confirmed only the two business tables and version ledger were added; extension
  names/versions were unchanged.
- [Upgrade SQL](sql/phase-1a-upgrade.sql) was generated and reviewed before application.
  It creates two business tables and one FK index, plus version bookkeeping. It has
  no business INSERTs, unrelated ALTER/DROP statements or extension operations.

## Focused checks

Command:

```sh
JOBMITRA_RUN_SCHEMA_TESTS=1 .venv/bin/pytest -q \
  tests/test_company_schema.py tests/test_company_migration.py
```

Result: **16 passed in 1.36 seconds**, no skipped tests or warnings. No full-suite run.

Coverage includes exact requested columns, unique normalized names, nullable address
fields, default empty PostgreSQL arrays, no-contact creation, multiple contacts and
phone strings, tracked in-place list edits, preserved company/contact IDs and source
IDs, leading zeroes, foreign-key rejection and restricted company deletion.
Migration tests verified metadata agreement, upgrade/downgrade/upgrade, rejection
of NULL array elements, and preservation of an unrelated sentinel table and pgvector.

Live tests used per-test disposable schemas with an outer transaction. All synthetic
rows, schemas and test version tables were rolled back. The applied business tables
were never used for test fixtures. The obsolete Phase 0 empty-metadata assertion was
removed in favor of the focused exact-two-table check.

Ruff lint and formatting checks passed for the implementation, migration, tests and
offline cleaning script. No broad test run or unrelated module implementation occurred.

## Cleaned workbook

Output: [company-dataset-cleaned.xlsx](../outputs/phase-1a/company-dataset-cleaned.xlsx).

- 180 original source entries → 166 normalized company-name candidates.
- 14 repeated-name groups consolidated without discarding distinct information.
- 159 preserved contact-text records. These are not 159 verified separate people;
  ambiguous delimiters remain unsplit and are flagged.
- 37 manual-review items affecting 39 company candidates: 11 differing-detail merge
  groups, 9 similar-name pairs, 10 contact splits, 7 cross-name shared-phone groups.
- Similar but nonmatching names remain separate. Candidate consolidation does not
  approve ambiguous company identities for future import.
- Every original Register ID survives. All distinct company-scoped phone values,
  contact text and original company-name spellings survive.
- All four address fields and unsupplied designations remain blank. No missing
  values or person-to-phone associations were guessed; source phones stay general.
- Four worksheets: Companies, Contacts, Review, Source Rows. All 180 original rows
  are copied with source Excel row numbers for traceability.
- All four sheets were rendered and inspected. Independent read-back reconciled
  every exported value, filter tables, frozen panes and the editable review dropdown.
  No spreadsheet formula errors were found. There are no formula cells in the output.
- Workbook authoring used the bundled Artifact Tool; source extraction/read-back used
  read-only operations. No original Excel write occurred.

Original workbook SHA-256, unchanged:
`97936c31d1bc52ccad2f78a347c741118e1557204066ec63b56e0102aee342c0`.

## Limits and next boundary

The implemented scope is the two-table schema, migration and separate cleaned output.
CRUD endpoints, UI, audit history, JD models, vector matching and data import are not
part of this change. Array source IDs require global ownership checks in any future
importer. Raw/bulk SQL must use the same name normalizer and explicit timestamp policy;
the ORM hooks are the supported editing mechanism. Manual review decisions must be
resolved before a later authorized import. Stop after Phase 1A.

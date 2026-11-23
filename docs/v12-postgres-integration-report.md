# V12 PostgreSQL development verification — 23 November 2026

This is the historical Phase 3 checkpoint before the separately approved final
header alignment, unified new-upload paths and release commit. The generated
template hash and uncommitted HEAD statements below describe that earlier checkpoint.
See [the final release report](v12-final-release-report.md) and
[Windows CMD runbook](v12-windows-postgresql-validation.md) for the release state.

Development integration passed. No production cutover, commit or push was performed.
The application ran on macOS against the actual Windows PostgreSQL server at
`192.168.1.51:5432`, database `jobmitra_dev`, using only the approved writable
`jobmitra_v12_dev_20261123_integration` schema for V12 changes.

## Data isolation and recovery evidence

A fresh 388,438-byte PostgreSQL custom-format backup was inspected and fully
restored into a disposable Unix-socket-only PostgreSQL cluster. SHA-256:
`e6b8845197bfefbc70aa4b15e04de53b53711dae6f425c71a04efb96de1bcd76`.
It is retained outside Git in
`/Users/mac/Documents/jobmitra/protected-backups/v12-postgres-integration/20261123T090440Z/`.

The explicitly approved server-side PostgreSQL copy reconciled all 664 application
rows and 779 identity/classification entries before commit. No second SQLite
import was performed. Existing development/test classifications remain preserved.

Final independent verification compared full protected-row fingerprints and sealed
metadata with the restored backup, and compared schema-only dumps byte for byte,
including owners, permissions, constraints, indexes, functions and freeze guards.

| Protected source | Verification |
| --- | --- |
| `public`, 16 legacy tables | All row fingerprints and DDL/ACL unchanged; 187 candidates and 136 companies |
| `jobmitra_v12_stage` | All 664 application rows and metadata unchanged; all 16 freeze guards retained |
| Original SQLite V2 and V3 | File SHA-256 unchanged |
| Existing `.env` | File SHA-256 unchanged |
| Approved original HTML | `a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e`, unchanged |
| `templates/v12/approved.html` | `e65f166197d4507df0b5df814ef803c6e92bf34910fd639d51978c68c7351a8b`, unchanged |
| Existing Email Studio files | No Git differences |
| 15 available original document files | Original sizes and SHA-256 unchanged |

The final development schema contains 724 application rows, including one clearly
labelled verification candidate, company and JD. Its counts are 191 candidates,
140 companies, four JDs, 24 resume metadata rows and 330 recruitment events.
The original 187 candidate PostgreSQL identity mappings and all 779 lineage
entries remain present. Development fixtures are retained as evidence.

Private detailed evidence is in `final-phase3-verification.json` in the backup
directory and `runtime/v12-postgres-readonly/native-pg-smoke-report.json`.
Private data, document bytes, screenshots and runtime reports are not staged.

## Verification results

| Area | Result and evidence |
| --- | --- |
| PostgreSQL adapter and business services | 37 focused tests passed on disposable PostgreSQL schemas, including clone reconciliation, rollback, duplicate races, concurrent selections, exact JSON/Decimal preservation and opaque imported round IDs |
| SQLite jobs, candidate editing and parsed documents | 47 focused compatibility tests passed |
| Startup and private proposal/resume storage | 88 tests passed; one native Windows-only test skipped on macOS |
| Additional approved-service batch | 91 tests passed before the final opaque-round-key correction; overlaps the focused batches above and is not an additional unique total |
| Actual Windows PostgreSQL development HTTP workflows | 39 checks passed, including three browser saves independently read back through canonical APIs |
| Companies | Canonical creation/contact IDs, browser company/contact edits, placement data and history passed |
| Candidates | Registration replay, precise salary edits, dashboard/directory date/source filters and professional search passed |
| Resume/parsed workflows | Original/altered uploads, exact downloads, selective JSON approval and original JSON bytes passed |
| JD Tracking | Creation, configured rounds, attachment, progression, interview activity, feedback, selection, joining and replay passed |
| Candidate eligibility | Joined candidate allocation blocked; exactly one selection and joining event after retries |
| Proposal documents | PDF generation/replay, hash/readability, signed-copy exact bytes, explicit acceptance and original PDF preservation passed |
| Email Studio | All four read-only pages and canonical candidate/JD email context passed; no email sent |
| Browser | Candidate, company/contact and JD edits saved without unlock prompts; API read-back passed; zero JavaScript console errors/warnings and no failed API response statuses observed |
| Static checks | Ruff, Python AST syntax, JavaScript syntax, generated-artifact check and Git whitespace checks passed |

The complete 472+ test suite was not run. Mac Windows-API simulations are not
native Windows filesystem results. The actual database engine runs on Windows;
the application process and filesystem checks ran on macOS.

All 58 SQLite trigger responsibilities are mapped in
[the parity audit](v12-postgres-trigger-parity.md). The development schema has 37
enabled consolidated guards/audits and no unvalidated constraints. Short writers
serialize with a schema-scoped advisory transaction lock; row locks, constraints,
partial unique allocation indexes, stale checks and idempotency receipts provide
additional protection. Physical entity deletion is deliberately stricter than
SQLite's nonreferenced-company deletion; archive/retire workflows remain intact.

## Presentation verification

No layout, CSS, original reference HTML, Jinja template, Email Studio page or PDF
design was changed. Eight generated status/footer strings became backend-neutral
so PostgreSQL actions no longer claim to save into SQLite. The generator reproduces
the checked artifacts exactly. Full bootstrap JSON matched the pre-batching result
byte for byte after canonical serialization; observed LAN latency fell from
21.075 seconds to 3.983 seconds.

Screenshots use desktop 1465×900 and mobile 390×844 viewports:

| Page | Approved reference | Integrated PostgreSQL |
| --- | --- | --- |
| Companies desktop | [Reference](../output/playwright/phase3-reference-companies-desktop.png) | [Integrated](../output/playwright/phase3-postgres-companies-desktop.png) |
| Candidate Search desktop | [Reference](../output/playwright/phase3-reference-candidates-desktop.png) | [Integrated](../output/playwright/phase3-postgres-candidates-desktop.png) |
| JD Tracking desktop | [Reference](../output/playwright/phase3-reference-jobs-desktop.png) | [Integrated](../output/playwright/phase3-postgres-jobs-desktop.png) |
| Companies mobile | [Reference](../output/playwright/phase3-reference-companies-mobile.png) | [Integrated](../output/playwright/phase3-postgres-companies-mobile.png) |
| Candidate Search mobile | [Reference](../output/playwright/phase3-reference-candidates-mobile.png) | [Integrated](../output/playwright/phase3-postgres-candidates-mobile.png) |
| JD Tracking mobile | [Reference](../output/playwright/phase3-reference-jobs-mobile.png) | [Integrated](../output/playwright/phase3-postgres-jobs-mobile.png) |

Reference screenshots contain the original demonstration data and preview banner.
The established production integration already replaces demo/reset actions with
canonical workflows, adds the implemented proposal action and positions its three
navigation tabs at the right. Dynamic names, counts, dates, selected records and
those pre-existing integration differences prevent a whole-image pixel-equality
claim. This phase preserves that implemented presentation and approved styling.
Screenshots remain private, ignored artifacts.

## Document and Windows limitations

Fifteen available documents were copied into disjoint development roots and
downloaded with verified size/SHA: ten resume files, four proposal PDFs and one
historical received signed-copy fixture. Seven unresolved historical file
references remain unchanged and correctly return unavailable responses. Three
other resume records are JSON/text-only. Missing files were not reconstructed.

Before Windows use, transfer verified physical bytes and private manifests outside
Git, configure Windows NTFS roots, and run native ACL/junction/reparse-point,
hard-link, upload/download, DOCX and startup checks. The backend does not need the
Mac SQLite database. This task did not transfer documents to the Windows filesystem.

The server currently provides no TLS. The explicit trusted-private-office-LAN
exception is used only as previously approved. Verified TLS or an approved tunnel,
a least-privilege runtime database role, native Windows validation, source-data
eligibility approval and load/cutover/rollback review remain production gates.
Direct editing is optional and restricted to direct loopback access; protected
deployments retain capability checks and business validation.

Windows environment variables, locked dependencies, exact startup command, URLs,
document copy procedure and rollback steps are in
[the development runbook](v12-postgres-development.md).

## Source changes

New implementation files:

- `src/jobmitra/modules/ats_v2/postgres.py`, `postgres_runtime.sql`, `postgres_rules.sql`, `resume_storage.py`
- `scripts/prepare_postgres_v12_dev.py`, `scripts/copy_v12_dev_documents.py`
- `tests/test_v12_postgres_backend.py`, `tests/test_v12_resume_storage.py`
- `docs/v12-postgres-development.md`, `docs/v12-postgres-trigger-parity.md`, this report

Modified tracked files:

- `src/jobmitra/core/config.py`, `local_v12.py`; `src/jobmitra/main.py`
- Under `src/jobmitra/modules/ats_v2/`: `approved.py`, `approved_router.py`,
  `candidate_profiles.py`, `candidate_registers.py`, `candidates.py`, `companies.py`,
  `database.py`, `jobs.py`, `parsed_documents.py`, `profile_store.py`,
  `proposal_documents.py`, `proposal_storage.py`, `proposal_store.py`,
  `proposal_windows.py`, `registration_store.py`, `request_receipts.py`, `resumes.py`,
  `router.py`, `schemas.py`, `unified.py`, `unified_access.py`
- `scripts/build_approved_v12.mjs`, `src/jobmitra/static/ats_v2/approved.mjs`
- `tests/test_v12_default_startup.py`, `tests/test_v12_proposal_pdf.py`

Other pre-existing untracked staging/history/reference files were preserved.
No files were staged. HEAD remains
`90654a8e955fb34d7b71ee051352821e165b6ba2` on
`feature/unified-workspace-v12`. No production backend configuration, NSSM service,
firewall rule, retained stash, commit or GitHub push was changed.

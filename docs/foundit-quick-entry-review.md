# Foundit quick entry and save diagnosis

## Confirmed behavior

Reproduced the supplied synthetic Kartik Jain profile in the original UI with disposable PostgreSQL. Save without the identity checkbox stopped in JavaScript with “Confirm identity, contacts and reviewed values before saving.” Checking it without Working as stopped with “Choose Working as before saving.” Neither attempt sent a create request. After satisfying both gates, the same profile saved successfully. The downloaded draft's field structure, with synthetic contact substitutions, also passed the original Pydantic validation, including blank domains and Unknown salary period.

These are confirmed UI save blockers, not evidence of a database connection failure. No production request log was provided, so the precise sequence behind the user's earlier failed attempt cannot be established from the draft alone. Download Reviewed Draft never saves to PostgreSQL.

## Changes

- `src/jobmitra/modules/candidates/foundit.py`: optional staff attribution for basic registration/update, explicit separate-person duplicate flag, ignore Enriched platform label, suggest the standalone city, flag ended employment under a Current source label, preserve the institution's comma-separated wording.
- `src/jobmitra/modules/candidates/router.py`: allow the explicit separate-person override through the existing CandidateCreate service.
- `src/jobmitra/modules/candidates/service.py`: unchanged shared contacts no longer block a role-only update; changing contact values still checks duplicates and keeps existing strict Foundit rules. Transactions and optimistic versions remain intact.
- `src/jobmitra/templates/candidates/foundit.html`: eleven default editable fields, compact supplied notice, collapsed Additional Parsed Details, one Save Candidate action, no basic-registration identity checkbox, field errors and Open Candidate Profile.
- `src/jobmitra/static/candidates/foundit.mjs`: automatic contact matching, explicit Update Existing / Create New separate-person choices, selected-field updates, optional attribution, error handling that retains edits, success only after successful API response, optional draft download.
- `src/jobmitra/static/candidates/desk.css`: compact fields and sticky save area for desktop/mobile.
- `src/jobmitra/templates/candidates/catalog_fields.html` and `src/jobmitra/static/stage2/catalog.mjs`: let Foundit hide catalog-add controls without affecting existing catalog-management forms.
- `tests/test_foundit_parser.py`, `tests/test_foundit_workflows.py`, `tests/test_foundit_quick_entry.py`: exact sample, updated workflow expectations, committed persistence and explicit duplicate choices.

No schema changes or new migrations. Unrelated pending JD/catalog changes remain untouched and uncommitted.

## Verification

31 focused parser/workflow tests passed, plus the existing Candidate Desk duplicate regression (1 passed). Ruff, JavaScript syntax and diff whitespace checks passed. Existing Starlette/httpx deprecation warning remains.

The supplied sample parses to 28 months, INR 350000 with Unknown period, Indore, valid footer phone/email, skills and preferred locations. Lower-case glued role/employer wording is left unresolved and editable; no employer boundary is invented. The Current-labelled job ending Jun 2023 is explicitly uncertain, not a current-employment fact.

A new test uses actual committed transactions, then a fresh SQLAlchemy Session and a second application client to verify persisted data. It verifies Directory/profile visibility, repeat-save rejection, explicit separate-person creation, version conflict rejection and selective updates preserving other values. Candidate visits, job-search requests, candidate documents and companies are unchanged. Prior document-byte preservation assertions continue to pass.

Browser verification at desktop 1440×1200 and mobile 390×844: all eleven core fields editable; advanced panel initially collapsed; no Add New Domain button; invalid-email inline error; save without staff selection; duplicate choices; role-only update; simulated HTTP 503 retains edits; retry succeeds; Directory and profile reload retain the candidate; mobile scrolling/save works with no document-width overflow. Synthetic candidate ID e98c976e-fa85-4c84-88f6-d3ea3bb8e50d belongs only to the disposable preview database and is discarded on shutdown.

Screenshots: `output/playwright/foundit-quick-desktop.png`, `foundit-quick-mobile.png`, `foundit-quick-mobile-saved.png`.

## Persistence

The core fields persist in existing candidate columns: name, mobile, email, total months, salary amount/period, role, city, skills, preferred locations and full qualification. Source remains Foundit. Supplied notice, original salary wording, explicit relocation and intentionally selected domain/subdomain use existing supported columns.

Industry, employer/employment history, separate institution/year and original pasted source/evidence remain explicitly draft-only and downloadable. They are not included in the saved profile payload and do not block core registration. No new consent records, visits or job-search requests are created.

No Windows PostgreSQL access/migration, real candidate/company edits, Git commit, push, scraping or external AI calls were performed.

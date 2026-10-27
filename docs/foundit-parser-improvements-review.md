# Foundit parser improvements — local review

## Changes in this task

- `src/jobmitra/modules/candidates/foundit.py`: scan contacts throughout the paste, validate Indian mobile length without guessing, keep contacts out of industry/employment, recognize past employment and industries, return editable structured job records, suggest institution/year conservatively, and parse explicit relocation values. Preserve original education wording. Require valid Indian mobile on Foundit confirmation only.
- `src/jobmitra/templates/candidates/foundit.html`: organized review sections, relocation selector, collapsed evidence, draft download and clear persistence labels.
- `src/jobmitra/static/candidates/foundit.mjs`: editable employment and additional fields, inline warnings, draft export, selective-save status and unsaved-draft protection.
- `src/jobmitra/static/candidates/desk.css`: section and uncertainty styling, responsive layout safeguards.
- `tests/test_foundit_parser.py`, `tests/test_foundit_workflows.py`: focused synthetic parser/persistence coverage.

Earlier company/catalog changes and the already-pending 0006 migration were left in place. This task created no migration and made no model/schema change.

## Findings and coverage

The actual defects were prefix-only contact scanning (contacts after industry were missed), contacts leaking into section values, lack of past-job segmentation, and incomplete review UI. Labelled contact followed by an unlabelled second contact also needed handling.

Existing experience conversion worked for the five requested cases: 5y 3m = 63, 2y 7m = 31, 4y 2m = 50, 6y = 72, 8m = 8. Tests establish this independently of previously manually corrected screenshots. Individual employment durations do not replace total experience.

Synthetic sales, auditor and senior-escalation profiles exercise footer contacts, current/past jobs, multiple past jobs, industries, preferred locations, skill deduplication and platform-label removal. Camel-case role/employer splits remain suggestions with explicit review warnings. Missing boundaries are retained as editable original wording rather than invented. Salary period remains Unknown unless explicit. Standalone LinkedIn/Newly added/All skills labels are excluded; genuine skills such as All skills Training are retained.

## Persistence today and proposed additive storage

Inspected Candidate SQLAlchemy model, CandidateFields/Profile schemas, Foundit confirmation routes, CandidateService create/update and repository duplicate/version behavior. Supported fields persist through the existing services: name, mobile, email, source, role, total months, domain/subdomain UUIDs, city, salary amount/period/raw wording, notice, skills, full qualification wording, preferred locations and explicit relocation preference.

No existing candidate column supports industry, employer names, employment history/dates, separate education institution/year or original Foundit paste/evidence. Resume parse storage is document/provider-specific and is not reused for this intake. Qualification retains its complete supplied wording; separate institution/year edits remain draft-only.

Proposed for separate approval: one nullable JSONB `candidates.foundit_details` column, with a typed/versioned payload for current/past industries, employment records, education details, original paste and review provenance. Existing rows remain NULL; no new tables, backfill or rewrite of confirmed fields. Future API updates must merge only selected reviewed keys under the existing candidate version lock. This proposal has NOT been implemented or migrated.

Until approval, all unsupported details are editable and clearly marked draft-only, included with original source and evidence in an explicit JSON download, and never represented as database-saved. Unsupported API keys are rejected rather than silently dropped. The download is a local review artifact, not a database save.

## Verification

29 focused tests passed (23 parser, 6 isolated PostgreSQL workflow tests). Ruff checks and JavaScript syntax validation passed. One existing Starlette/httpx deprecation warning remains; no dependency changes made.

Workflow tests verify repeated parsing writes nothing; employee-edited values persist; unselected fields, related tables and resume bytes remain unchanged; duplicates and stale versions are rejected; no automatic visits or job-search requests are created.

Playwright used a disposable local PostgreSQL app on 127.0.0.1:8766 with private temporary document storage, never the Windows database. Demo sequence: parse footer-contact sales profile → edit name → check duplicates → explicitly create → check duplicate → explicitly link → select role only → confirm save → read back preserved name and 63 months → download reviewed draft. Synthetic candidate ID: `4614e639-c0a2-44ac-bf2e-13de8ff17552` (temporary database, discarded on shutdown). A further role-only save verified the updated status at version 3. Mobile 390×844 and desktop 1440×1100 checks completed; no mobile document-width overflow.

Artifacts in `output/playwright/`:
- `foundit-improved-desktop.png`
- `foundit-improved-mobile.png`
- `foundit-employment-desktop.png`
- `foundit-employment-mobile.png`
- `foundit-synthetic-reviewed-draft.json`

No Windows access, live record changes, new migrations, Git commit or push occurred in this task.

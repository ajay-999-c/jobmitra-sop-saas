# Candidate Dashboard, Directory and registration purpose

Implemented and verified only on the separate `runtime/v12-candidate-registers/dev/ats.sqlite3` development copy. Preview: http://127.0.0.1:8004/workspace-v12/candidates?section=dashboard. No production or main-development migration was run.

- Existing `candidates.created_at` has a backend SQLite UTC default and an immutable identity/timestamp trigger. Edits update `updated_at`, and the Full Profile now displays the original registration date in Asia/Kolkata. No creation-date column was added.
- Existing canonical sources were MANUAL, WALK_IN, FOUNDIT_PASTE, RESUME_UPLOAD and OTHER. The main development snapshot held 173 Foundit, 14 Other, 2 Walk-in and 1 Manual candidates. Filtering uses canonical `candidates.source`, preserving original imported labels and raw evidence separately.
- Dashboard: All Time, Today, Monday-based Week, Month, Year and inclusive Custom dates, combined with canonical source filters. SQLite returns filtered registration counts/recent registrations. Total Candidates (All Time), JD linkage and readiness metrics remain unfiltered. Clear Filters is independent of Directory.
- Directory: basic name/mobile/email/title search, the same date/source utilities, newest-created-first sorting, accurate counts, and server-side pages of 20/50/100. Selected, Joined and Not Joined candidates remain visible. Full Profile buttons use canonical IDs. No advanced Candidate Search matching logic changed.
- Optional Purpose of Visit / Registration is stored initially in the existing immutable REGISTRATION_DETAILS audit event, against the new canonical ID. The existing typed candidate-profile history stores subsequent reviewed purpose edits, with optimistic revision and before/after audit. Clearing it remains explicit; the original purpose evidence is retained. Full Profile and Complete Edit show the field; older/imported records show Not recorded. No visit or job-search activity is created. Foundit can omit the field.

## Development schema change

Email was unsupported by both the input validator and the SQLite source CHECK. Optional **registration extension v1** adds canonical EMAIL without converting it to OTHER. SQLite cannot directly ALTER a CHECK constraint, so the explicit installer atomically recreates only the candidate table definition in an exclusive transaction on an isolated runtime/ copy. Every original value and row is copied and reconciled; indexes, triggers, views, foreign keys, original timestamps, IDs, source JSON and salary precision are preserved. Unrelated schema objects remain identical. A small immutable version-marker table records the extension; base SQLite `user_version` remains 3.

The installer refuses non-runtime paths and V2 databases. A forced mid-install failure was tested to roll back all rows and schema objects and restore foreign-key enforcement. Repeating installation is a no-op. Startup validates either exact supported schema; it never migrates. EMAIL writes to a store without the extension are refused, not remapped. Purpose requires no new column/table and reuses the existing optional typed profile extension.

For a separately approved isolated copy only:

```bash
.venv/bin/python -m jobmitra.modules.ats_v2.registration_store --database runtime/PATH/ats.sqlite3
```

No production migration is supplied or invoked by this workflow. The main `runtime/v12-local/ats-v3.sqlite3` remains unchanged; the port-8004 preview has the extension and the two clearly named synthetic registrations used for testing.

## Exact files changed

New:

- `src/jobmitra/modules/ats_v2/candidate_registers.py`
- `src/jobmitra/modules/ats_v2/registration_store.py`
- `src/jobmitra/modules/ats_v2/registration_schema.sql`
- `src/jobmitra/static/ats_v2/candidate-registers.mjs`
- `tests/test_v12_candidate_registers.py`
- `docs/v12-candidate-registers.md`

Updated:

- `src/jobmitra/modules/ats_v2/approved.py` — optional purpose evidence, canonical source metadata.
- `src/jobmitra/modules/ats_v2/approved_router.py` — the two registration read APIs.
- `src/jobmitra/modules/ats_v2/database.py` — exact optional extension validation.
- `src/jobmitra/modules/ats_v2/candidate_schemas.py` — canonical EMAIL input value.
- `src/jobmitra/modules/ats_v2/candidates.py` — reject unsupported EMAIL writes; no matching behavior change.
- `src/jobmitra/modules/ats_v2/candidate_profiles.py` — typed purpose and initial-evidence fallback.
- `src/jobmitra/static/ats_v2/candidate-desk.mjs` — one optional purpose edit field and supported Email source choice.
- `src/jobmitra/static/ats_v2/approved-api.mjs` — project creation date and current purpose to the existing profile.
- `scripts/v12-adapters/candidates.js` — registration payload/source mapping and narrow Dashboard/Directory delegation.
- `scripts/build_approved_v12.mjs` — additive controls/profile fields and module integration from immutable source.
- `src/jobmitra/static/ats_v2/approved.mjs` — reproducibly generated runtime.

## API mapping

- `GET /api/v12/approved/candidate-dashboard`: `period`, optional `date_from`, `date_to`, `source`; total, selected-period count, recent registrations and calendar bounds.
- `GET /api/v12/approved/candidate-directory`: same filters plus `q`, `page`, `page_size`; rows, total and pagination.
- Existing `POST /api/v12/approved/registration`: optional `registration_purpose`; canonical EMAIL when the extension is installed.
- Existing candidate `/profile` GET/PATCH and `/profile-history`: purpose read/edit/audit with unchanged transaction/revision controls.

## Focused verification

14 targeted Python cases passed across the new focused test group and the existing Foundit intake/enrichment check. They cover IST midnight boundaries, Monday week, month/year and inclusive custom ranges; source combinations; name/mobile/email/title searches and literal escaping; counts/newest order/pagination; optional and edited purpose; immutable timestamps; selected/joined/not-joined visibility; extension reconciliation/idempotency/rollback/V2 and path refusal. Ruff, lightweight JavaScript syntax and reproducible-build checks passed. The complete Python/JS regressions, external AI/OCR and unrelated Companies/JD/Email browser workflows were not run.

Actual browser/API read-back verified registration with Email and purpose, registration without purpose, purpose edits with unchanged creation timestamp, original Full Profile buttons, each Dashboard preset and combined Custom+Email, four Directory search fields, 20-row pages with no overlap, independent filter/clear state, and desktop/mobile usability.

In the isolated copy after two synthetic registrations: Total Candidates remained 192 across filter changes; Today returned 4, Week 42, Month 135, Year 192, and Custom 20 November + Email returned 1. Directory reported 192 rows across 10 pages of 20. These are test-copy counts, not production counts.

Screenshots:

- [Dashboard desktop](../output/playwright/v12-candidate-dashboard-filters-desktop.png) / [mobile](../output/playwright/v12-candidate-dashboard-filters-mobile.png)
- [Directory desktop](../output/playwright/v12-candidate-directory-filters-desktop.png) / [mobile](../output/playwright/v12-candidate-directory-filters-mobile.png)
- [Registration purpose](../output/playwright/v12-registration-purpose-desktop.png) / [mobile](../output/playwright/v12-registration-purpose-mobile.png)
- [Full Profile date/purpose](../output/playwright/v12-registration-purpose-profile.png)

The Directory itself filters/paginates on the server. The existing shared workspace bootstrap still loads canonical projections for the other approved workflows; it was not redesigned in this task. Filters are independent in-memory view state, not browser-local master data or durable saved filters.

## Preservation

Every pre-existing relational row in the test copy is unchanged, including imported identities/timestamps, resumes and historical events. Its integrity and foreign-key checks pass. The main development database equals its pre-request snapshot. Production ATS/Resume Processor rows/schema/artifact hashes match protected checkpoints. No PostgreSQL writes or production connection was used.

Original approved HTML SHA-256 remains `a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e`. Original reference HTML, standalone/embedded Email Studio, Companies/JD component markup/styles/logic, proposal code/templates/PDF design and parsed resume code are unchanged. No Git pull, reset, clean, stash change, commit, push or deployment.

# V12 local startup and Company Proposal integration

Implemented and verified on `feature/unified-workspace-v12`, 20 November 2026.
No production cutover, migration, commit, push or stash change was performed.

## Startup and routing

The previous `/` handler always redirected to `/overview`, and the normal configuration
has V12 disabled against SQLite V2. Selecting another Uvicorn port did not select a frontend.

When `unified_v12_enabled` is explicitly true, `/` and `/overview` now issue a 303 redirect
to `/workspace-v12/companies`. Normal mode keeps the legacy landing page and APIs.
The V12 routes still require a compatible V3 store; a V2 store returns 503 and is never upgraded.

Run from the project directory:

```bash
JOBMITRA_LOCAL_V12=1 .venv/bin/python -m uvicorn jobmitra.main:app --app-dir src --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Then open **http://127.0.0.1:8000/**.
The server is already running with this profile after verification; do not start another process on the occupied port.

The explicit `JOBMITRA_LOCAL_V12=1` profile:

- Uses only the existing `runtime/v12-local/ats-v3.sqlite3` and `runtime/v12-local/resumes`.
- Explicitly enables `unified_v12_local_direct_editing` with the declared actor `Local development user (unverified)`. No shared key/session or editing prompt is required; the old access-key file is not read or modified.
- Bypasses `.env` and inherited production database/storage values for its database paths and credentials.
- Sets the unused legacy PostgreSQL connection to loopback port 9, preventing access to the production server.
- Refuses missing, symlinked/hard-linked or V2 database files; it never initializes or migrates anything at startup.
- Leaves resume processing/AI disabled. Direct editing is restricted to loopback peers, socket addresses and Host values; forwarded requests are refused. Non-loopback Uvicorn CLI bindings fail closed. Normal production configuration retains capability checks.

The local directory was prepared once from the already isolated approved V3 preview and its resume copies.
Existing files were not overwritten. No production database was used as a writable source or target.
A fresh machine needs an explicitly prepared V3 development copy in this directory before using the profile;
startup deliberately does not create, copy or migrate a database automatically.

Direct routes remain `/workspace-v12/companies`, `/workspace-v12/candidates`, and `/workspace-v12/jobs`.
Tab changes and programmatic workspace navigation update browser history. Back/forward activates the matching
workspace; reload/deep links use the server-selected section. The original workspace components are retained.
Legacy PostgreSQL APIs remain registered; exercising those against PostgreSQL requires their normal separately
configured environment. The isolated profile intentionally does not contact production PostgreSQL.
The older port-8768 process was left running; port 8000 is the verified current integration.

## Company Proposal

Entry point: **Companies → selected company → Details & contacts → Prepare Proposal**.
The compact action is in the existing header beside View company JDs. No original control was removed.
The generated UI gained only a canonical selected-company getter; its markup, styles and templates were not regenerated.
The original reference HTML remains byte-identical.

The existing Email Studio overlay now hosts either of two original composers:

1. **Proposal & terms · 6% / 8.33%**: the existing `Jobmitra_Company_Proposal_Studio.html`, copied unchanged
   from Downloads into application resources. Both rates, their approved 21/30-day equivalents, the existing
   custom-rate control and all ten commercial clauses remain intact. Existing preview, subject copy,
   formatted copy and HTML download actions are reused.
2. **Original 8.33% DOCX & cover email**: the existing `/email/proposal` page and embedded Word proposal.
   Its wording, subject, downloadable document and business terms remain untouched.

Source for the dual-rate composer:
`/Users/mac/Downloads/Jobmitra_Company_Proposal_Studio.html`.
Exact source/resource SHA-256:
`cb3f47308cb7dac56c48fef38be958a145e9db5faa96575226668767b4b56d40`.

The parent adapter passes canonical company/contact UUIDs, reads validated context, and prefills the original
company/contact fields. Active contacts only are selectable. Changing contact preserves the chosen fee and
updates the recipient; controls pause while the new context is being fetched. Foreign or archived contact IDs
are rejected. A missing email stays blank with an editable To field. Copy To/manual edits do not update a master.
The demo-data control in the embedded dual-rate composer reloads canonical company details instead of loading examples;
its standalone source bytes remain unchanged.

New read-only endpoints:

- `GET /api/v12/approved/companies/{company_id}/proposal-context?company_contact_id=...`
- `GET /api/v12/approved/companies/{company_id}/proposal-studio?company_contact_id=...`

No JD or candidate is required. There is no send endpoint, automatic attachment/delivery, proposal-history insert
or SENT event. Existing infrastructure has no approved proposal-history contract; persistent proposal history
therefore remains a reported gap. No new database table or schema/API mutation was introduced.

## Verification

| Check | Result |
|---|---|
| V12 `/` and `/overview` | 303 → `/workspace-v12/companies`; real browser confirmed |
| Three direct workspace routes | HTTP 200 with the approved template |
| Legacy root in normal mode | Still redirects to `/overview` |
| Tab URL / back / forward / deep-link reload | Passed in real browser after workspace bootstrap |
| Incompatible V2 / missing local store | Refused; every original row/schema object unchanged |
| Correct company and selected active contact | Canonical IDs, name and email read back through API and browser |
| Alternate contact | Accurate prefill; existing 8.33% fee stayed selected |
| Missing contact email | Blank; manual recipient copied; master email remained blank |
| Cross-company/archived contact | Rejected with 422; unknown company 404 |
| 6% / 21-day and 8.33% / 30-day terms | Original controls exercised; actual clipboard contents verified |
| Original 8.33% DOCX | Download verified: every file part matches the embedded original, except its approved client-name placeholder replacement |
| Preview / copy / manual recipient | Exact API state before/after identical; no sent events |
| Original reference / Email Studio | Hashes and standalone response bytes unchanged |
| Existing candidate/profile/resume/JD/Email regressions | Full suite passed |
| Local SQLite integrity / foreign keys | `ok`; zero violations |

Python: **405 + 28 = 433 passed**, **16 skipped**.
The skipped opt-in tests are six legacy company imports, seven legacy company UI tests and three live-database
integration checks; they are not counted as passes. PostgreSQL tests that ran used a disposable Unix-socket cluster.
JavaScript: **20 passed**. Ruff, JavaScript syntax and generated-artifact byte checks passed.
No existing test database or production database was initialized or upgraded.

Screenshots (desktop 1440×1000, mobile 390×844):

- [Company action — desktop](../output/playwright/v12-proposal-company-action-desktop.png)
- [Company action — mobile](../output/playwright/v12-proposal-company-action-mobile.png)
- [Proposal — desktop](../output/playwright/v12-proposal-desktop.png)
- [Proposal — mobile](../output/playwright/v12-proposal-mobile.png)

Private test evidence is in ignored `runtime/v12-startup-proposal/`.
The extra company/contacts used for browser verification are synthetic and exist only in the isolated local copy.

## Changed files for these two improvements

- `src/jobmitra/core/config.py`, `core/local_v12.py`: explicit isolated startup profile.
- `src/jobmitra/modules/companies/router.py`, `modules/jobs/router.py`: mode-aware landing redirects.
- `src/jobmitra/modules/ats_v2/approved_router.py`, `proposal.py`: read-only company proposal context/resource.
- `src/jobmitra/static/ats_v2/v12-shell.mjs`, `v12-shell.css`: URL/history synchronization and compact proposal adapter.
- `src/jobmitra/static/ats_v2/approved-api.mjs`: load that separate adapter.
- `src/jobmitra/static/ats_v2/approved.mjs`: expose the current canonical company ID (no markup/style changes).
- `scripts/build_approved_v12.mjs`: retain that getter in the reproducible generation recipe; check mode only was run.
- `src/jobmitra/modules/email_studio/resources/Jobmitra_Company_Proposal_Studio.html`: exact existing dual-rate source copy.
- `tests/test_v12_startup_proposal.py`: isolated routing, schema safety, local profile, ownership and no-write regressions.
- `.env.example`, `README.md`, this report: local command and integration documentation.

## Preservation and remaining boundaries

Original V12 reference SHA-256 remains
`a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e`.
All pre-existing standalone Email Studio HTML, router and template files are byte-identical.
Production SQLite V2 and Resume Processor every-row/schema comparisons match the protected pre-V12 backups;
original artifacts, checkpoint HEAD and retained stash remain unchanged. Production PostgreSQL was not contacted or modified
by the local application or these tests. No production migration/deployment or commit/push was performed.

Remaining boundaries: no persistent proposal-history contract; no automatic send/attachment; the existing
Word template is the approved 8.33% document (a 6% Word document was not invented). Production cutover remains
separately authorized work.

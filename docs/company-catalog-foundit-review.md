# Existing-company selection, shared catalog and Foundit paste — local review

Implemented in the existing unified FastAPI/Jinja application. No separate app,
external AI, Foundit scraping or WhatsApp integration was introduced.

## Schema inspection and migration

Read-only inspection on 2026-10-22 confirmed Windows PostgreSQL is at
`0005_jd_general_skills`. Candidates already reference `work_domains` and
`work_subdomains` by UUID. JDs only had free-text `domain_key`/`subdomain_key`.

Prepared `0006_jd_catalog_links`, following 0005. It adds only nullable
`job_requirements.domain_id` and `subdomain_id`, a domain foreign key, a composite
subdomain/parent foreign key and a parent-presence check. Foreign keys restrict
parent deletion. There are no new tables, backfills, catalog seeds or alterations
to candidate/company/resume records. Historical JD classification text remains
stored separately and appears as read-only context on the form.

The migration was applied only inside disposable local PostgreSQL clusters. The
application now expects these columns: do not deploy this code against Windows
0005 until migration 0006 receives separate approval. No commit or push was made
for this implementation.

Candidate schema needs no migration for the supported intake fields. Employer,
industry, original employment text/dates and collection method have no matching
candidate columns. These remain clearly labelled, editable preview-only details;
they are not silently mapped into domain, qualification or another unrelated field.
Persisting these details would require a separately reviewed schema decision.

## Behavior and call paths

- JD company search filters actual Company Directory rows in a native keyboard
  accessible select. Search text is never submitted as a company ID. Existing
  company/contact validation and immutable UUID relationships remain in place.
- JD and Candidate forms share `catalog_fields.html` and `catalog.mjs`. They use
  the existing `/api/domains`, `/api/subdomains` and `DomainCatalogService`.
  Inline Add New actions refresh and select the created label. Changing a parent
  clears its subdomain; the server also rejects a mismatched parent. Existing
  inactive references remain selectable for their current record. Job role/title
  remains free text. Catalog changes do not automatically rewrite legacy labels.
- `GET /candidates/foundit-import` appears under Candidate Desk → Foundit Paste.
  `POST /api/candidates/foundit/preview` calls the pure typed
  `parse_foundit_text` parser, with no database dependency or persistence.
- The parser supports labelled and common unlabelled text, repeated labels,
  comma/newline skills, common salary units and experience. All extracted values
  require confirmation. Conflicts and invalid formats produce evidence notes;
  no domain, consent, joining date, visit or search request is inferred.
- `GET /api/candidates/duplicates` now accepts mobile and/or email. It checks
  trimmed case-insensitive emails and phone digit keys, including common Indian
  country-code variants without rewriting existing stored phone values.
- `POST /api/candidates/foundit/confirm` validates confirmed identity and active
  staff, then uses `CandidateService.create_candidate(strict_contacts=True)`.
  It cannot override duplicate detection, use Walk-in source or create a request.
- `PATCH /api/candidates/foundit/{id}/confirm` uses the existing candidate service
  transaction and version check. The UI sends only explicitly checked fields;
  domain/subdomain are reviewed together. Unselected fields and linked records
  remain unchanged. The server checks contact conflicts at commit time, with
  advisory contact locks shared by ordinary candidate create/edit paths.
- Once linked/created, Save Reviewed Changes supports incremental explicit saves
  with Saving/Saved/Failed feedback. Automatic blur-save was deliberately avoided:
  it could persist a pasted suggestion before field-by-field review. Stale versions
  fail without auto-retrying; the draft remains available for comparison and relink.
  Unsubmitted employee edits stay flagged and trigger a leave-page warning.
- No raw paste or preview-only evidence is retained in the database, localStorage,
  logs or new files. The existing salary-original-wording field can be saved only
  as part of employee-confirmed candidate fields. No resume file/link code changed.

## Verification

- 13 parser unit tests passed: exact supplied sample, 63 months, INR 200000 with
  Unknown period, Immediate Joiner, Indore, industry separation, glued employment
  boundary, placeholders, repeated labels/skills, malformed salary/experience/email,
  and footer-only removal without correcting genuine skill spellings.
- 95 isolated PostgreSQL workflow/regression tests passed across
  `test_foundit_workflows.py`, `test_stage2.py`, `test_stage3.py`, `test_portal.py`.
  These cover zero-write preview, confirmed create/reload, duplicate contact review,
  selected updates, stale versions, unchanged related tables and resume bytes,
  shared catalog validation, company rename safety, and additive migration
  preservation. Existing cross-company contact rejection tests also passed.
- Ruff, JavaScript syntax and Git whitespace checks passed.
- Playwright exercised real local forms: company filtering and UUID save/edit,
  inline domain/subdomain creation shared across forms, parent reset, candidate
  creation, duplicate repeat import, manual link, selective update, simulated
  version conflict and retry, retained unsaved edits, keyboard search and mobile
  overflow. All browser writes used synthetic disposable data.
- Screenshots were visually inspected:
  - `output/playwright/foundit-desktop.png`
  - `output/playwright/foundit-mobile.png`
  - `output/playwright/foundit-mobile-review.png`
  - `output/playwright/jd-company-catalog-desktop.png`
  - `output/playwright/jd-company-catalog-mobile.png`

Existing office/DEMO data and production resume files were never used as write
fixtures. The only office database access was the read-only schema/revision check.

## Changed files

New:

- `migrations/versions/0006_jd_catalog_links.py`
- `src/jobmitra/modules/candidates/foundit.py`
- `src/jobmitra/static/candidates/foundit.mjs`
- `src/jobmitra/static/stage2/catalog.mjs`
- `src/jobmitra/templates/candidates/catalog_fields.html`
- `src/jobmitra/templates/candidates/foundit.html`
- `tests/test_foundit_parser.py`
- `tests/test_foundit_workflows.py`
- `docs/company-catalog-foundit-review.md`

Modified:

- `src/jobmitra/modules/candidates/repository.py`
- `src/jobmitra/modules/candidates/router.py`
- `src/jobmitra/modules/candidates/schemas.py`
- `src/jobmitra/modules/candidates/service.py`
- `src/jobmitra/modules/jobs/models.py`
- `src/jobmitra/modules/jobs/repository.py`
- `src/jobmitra/modules/jobs/router.py`
- `src/jobmitra/modules/jobs/schemas.py`
- `src/jobmitra/modules/jobs/service.py`
- `src/jobmitra/static/candidates/desk.css`
- `src/jobmitra/static/candidates/desk.mjs`
- `src/jobmitra/templates/candidates/base.html`
- `src/jobmitra/templates/candidates/candidate_form.html`
- `src/jobmitra/templates/stage2/base.html`
- `src/jobmitra/templates/stage2/manual_fields.html`
- `tests/test_stage2.py` (head expectation and scope of the 0005-specific test)

User-supplied prompt/prototype and unrelated `docs/windows-installation.md` remain
untouched. Review this implementation and the additive migration before separately
authorizing any Windows deployment.

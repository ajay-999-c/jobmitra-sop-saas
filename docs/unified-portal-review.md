# Unified Jobmitra portal — implementation review

Base checkpoint: `15572f0` on `main`. No commit or push made by this integration.
All routers were already included once in `jobmitra.main:create_app`; no duplicate
mounts, alternate application, iframe or external frontend was added.

## Run one website

```sh
.venv/bin/python -m uvicorn jobmitra.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open `http://127.0.0.1:8000/`, which redirects to `/overview`. Restart the existing
backend to load changes. Every link below is relative to that same origin.
No module requires its own process or port.

For isolated review only, `scripts/test_stage3_isolated.py --serve` runs this same
app against a disposable PostgreSQL cluster and private temporary file root.
It now defaults to port 8000 and accepts `--port`. Browser verification used
`--port 8766` because an existing backend occupied 8000; **all** tested modules
ran on this single isolated origin. The previous isolated preview was stopped.
Neither the existing regular server nor Windows PostgreSQL was changed.

## Routes and local tabs

| Global section | Actual routes | Local navigation |
| --- | --- | --- |
| Overview | `/`, `/overview` | New JD, Add Candidate, Register Walk-in, View Companies; real company/candidate counts and JD status/target summaries |
| Companies | `/companies`, `/companies?company_id=UUID` | Existing search, editable details, contacts; View company JDs |
| JD Tracking | `/requirements`, `/requirements/new`, `/requirements/{id}` | Company filter; JD Overview, Criteria & Skills, ATS JSON, History, Candidate Pipeline; existing work-focus tracker |
| Candidate Desk | `/candidate-desk`, `/candidates`, `/candidates/new`, `/candidates/{id}`, `/office-visits`, `/job-search-requests`, `/domains` | Today, Candidates, Office Visits, Job Search Requests, Domain Catalog; profile Overview, Office Visits, Job Search Requests, Resumes & Parsed JSON |
| Staff | `/staff` | Existing active/inactive staff management |
| Tasks | `/tasks` | Existing staff/status filters and follow-up actions |

Existing `/api/...` write routes and document download paths are retained. Company
links use the actual company UUID, with an optional `company_id` filter on both
`/requirements` and `/api/jobs`. No candidate-to-JD association was added.
JD focus remains operational focus, not candidate progress or selection counts.

## Changed files and functions

- `src/jobmitra/templates/stage2/base.html`: the existing shared base now owns the
  sticky horizontal header, global active state, Working as selector and breadcrumbs;
  the permanent sidebar markup is removed. No duplicate header per feature.
- `src/jobmitra/static/stage2/portal.css` (new): shared red/navy portal styling,
  readable wider content, scrollable mobile navigation and company workspace sizing.
- `src/jobmitra/static/stage2/workflow.mjs`: centers the active link inside the mobile
  nav. Existing sessionStorage staff selection and mutation handlers are reused.
  Selection persists within the browser tab across module navigation; it is not login.
- `src/jobmitra/core/pages.py`: common template lookup includes Companies. `render`
  loads staff in a savepoint so a missing staff schema does not block Company pages.
- `src/jobmitra/modules/companies/router.py`: root redirects to Overview;
  `company_directory` renders through the shared renderer. CRUD services are unchanged.
- `src/jobmitra/modules/companies/templates/companies/directory.html`: extends the
  shared shell, retains directory/forms and adds the company-to-JD link.
- `src/jobmitra/modules/companies/static/directory.mjs`: `showForm` updates that link;
  a validated directory UUID in the URL opens the corresponding existing details.
- `src/jobmitra/modules/jobs/repository.py`: `directory` accepts an optional company
  UUID predicate. Existing query behavior is retained when no company is supplied.
- `src/jobmitra/modules/jobs/router.py`: forwards the company filter; `overview`
  reads real module counts independently and reports unavailable data truthfully.
- `src/jobmitra/templates/stage2/overview.html`: cross-module quick actions/counts,
  preserving the existing JD target list; no fabricated counts for missing schemas.
- `src/jobmitra/templates/stage2/directory.html`: retains the company filter through
  ordinary GET and HTMX filtering, with a link back to the selected company.
- `src/jobmitra/templates/stage2/workspace.html`: links back to the exact company,
  all JDs and Candidate Desk; tracker and internal panels unchanged.
- `src/jobmitra/templates/candidates/base.html`: contextual module heading and local
  tab active states; all Candidate Desk pages inherit the same global shell.
- `src/jobmitra/main.py`: `portal_error` supplies a navigable HTML 503 page for
  unavailable full-page modules. API, health and download error contracts remain intact.
- `src/jobmitra/templates/stage2/unavailable.html` (new): shared-shell unavailable page.
- `scripts/test_stage3_isolated.py`: configurable test-server port, default 8000.
- `tests/test_portal.py` (new): cross-module route/active-nav/filter/fragment tests
  and missing-schema handling using only the guarded disposable database.
- `tests/test_company_ui.py`: root redirect expectation updated to Overview.
- `README.md`, this document: one-server startup, route map and review instructions.

No models, migrations, business mutation services, dependencies or `.env` changed.
The user's untracked integration prompt is untouched and is not an application asset.

## Verification

Focused isolated test run: **10 passed in 1.34 seconds**, one existing
Starlette/httpx deprecation warning. No full suite was run.

```sh
.venv/bin/python scripts/test_stage3_isolated.py --pytest-args \
  tests/test_portal.py \
  tests/test_stage3.py::test_ui_pages_forms_email_states_and_local_assets \
  tests/test_stage3.py::test_registration_edit_email_salary_nulls_and_retained_identity \
  tests/test_stage3.py::test_upload_versions_download_integrity_and_latest_rule \
  tests/test_stage3.py::test_json_history_exact_version_review_and_no_profile_promotion \
  tests/test_stage2.py::test_pages_fragments_local_assets_and_no_fake_candidate_metrics \
  tests/test_company_ui.py::test_local_assets_and_invalid_inputs_without_database
```

Ruff for changed Python, Node syntax checks for changed JS, and `git diff --check`
passed. Initial new-test fixture naming errors were fixed before the passing run.

Playwright used synthetic records only. Desktop 1440×1000, mobile 390×844:
- Navigated JD → Candidate Desk, retaining Working as selection.
- Verified JD → exact Company → filtered JDs, with no company-page overflow.
- Mobile Add Candidate dialog: page width 390, internally scrollable body, footer
  bottom 831 within the 844 viewport.
- Global navigation works with JavaScript disabled, including scroll-hidden links.
- Saved an email edit through the candidate modal; the profile UUID was retained.
  Opened the Resumes & Parsed JSON panel in the same shell.
- Browser console: no errors or warnings during the checked navigation.

Screenshots are ignored local review artifacts:
[JD desktop](../output/playwright/unified-jd-desktop.png),
[Candidate Desk desktop](../output/playwright/unified-candidate-desktop.png),
[JD mobile](../output/playwright/unified-jd-mobile.png),
[Candidate Desk mobile](../output/playwright/unified-candidate-mobile.png),
[mobile candidate form](../output/playwright/unified-candidate-form-mobile.png).

## Manual review and deployment boundary

1. Start the single server and open `/`. Verify active tabs and all six destinations.
2. Select Working as; navigate Companies → JD Tracking → Candidate Desk and verify
   the selected active employee persists in the same tab.
3. Open a company, follow View company JDs, then a JD and its company backlink.
4. Check JD focus and internal panels; candidate profile edit, visit, search,
   document and JSON pages should retain their existing functionality.
5. At mobile width, scroll the top nav horizontally and open Add/Edit Candidate;
   verify internal form scrolling and visible Save/Cancel controls.

Windows migrations `0003`/`0004` remain subject to separate approval. Their current
remote state was not queried. Missing schema is not automatically created and the
application does not claim Candidate Desk persistence when unavailable. Production
resume storage configuration remains a separate existing prerequisite. No Windows
connection, migration, role change or live-data mutation occurred in this task.

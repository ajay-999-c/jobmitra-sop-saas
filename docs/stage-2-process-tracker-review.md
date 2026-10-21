# JD Process Tracker — review, 2026-10-21

Implemented in the existing Stage 2 workspace. **Pending Windows migration approval.**
The Windows database was inspected in a read-only transaction: revision
`0002_jd_tracking`, with no existing focus column. No Windows migrations or record
writes were performed. No legacy `RECRUITER_SCREENING` code was found in application
code or migrations, so no label/data conversion is needed. Revision 0002 was not edited.

## Behavior

The tracker sits immediately below the JD heading and above action controls/tabs.
It remains visible on Overview, Criteria & Skills, ATS JSON, History and Candidate
Pipeline. Its seven ordered steps are Candidate Pool, Candidate Contact, Jobmitra
Screening, Company Submission, Interviews, Selection and Joining.

Only the saved manual focus is red (`#dd0000`). All other steps remain neutral,
including earlier steps. An unset focus shows “Focus not set.” No candidate counts,
completion percentage or previous-stage completion is inferred. Candidate Pipeline
is explicitly “not connected.” A JD may have candidates in multiple stages.

Change Focus provides the seven choices and Clear focus. It uses the existing
Recording as selection, visibly self-selected/unverified. No reason, ownership or
handover input is added. Saving reloads the server-rendered page, so subsequent
loads on other devices see the persisted value. Already-open pages must reload;
there is no new polling or cache layer.

JD status and target milestone/date remain independent. Selection completion still
requires distinct company-confirmed selected candidates covering all known vacancies;
Stage 2 cannot verify that. Joining needs separate confirmation. Selecting either
focus does not complete a target or fabricate candidate evidence.

Edit JD, Manage Recruiters, Change Target and Change Status use compact controls
with equal 40 px collapsed heights at the checked desktop viewport. Existing forms
expand in normal document flow. The tracker scrolls horizontally on small screens.

## Backend and migration

`PATCH /api/jobs/{job_id}/work-focus` accepts:

```json
{
  "actor_staff_id": "<existing active staff UUID>",
  "version": 1,
  "current_work_focus": "CANDIDATE_CONTACT"
}
```

Use `null` or an empty string to clear. All other unsupported values are rejected.
The route uses the existing same-origin protection and returns `JobRead`, which now
includes `current_work_focus`.

`JobRequirementService.change_work_focus()` uses the existing locked JD/version
check and active-staff validation. `changes_for()` and `record_action()` update only
focus plus the existing version/timestamp, and append `WORK_FOCUS_CHANGED` with old
and new values. The existing Activity helper captures the staff ID/name snapshot and
timestamp. Both writes occur in one transaction; failures roll back both. Identical
values create no event or version increment. Stale versions return HTTP 409. History
shows readable old/new labels, with raw event detail available as before.

New revision: `0003_jd_work_focus`, parent `0002_jd_tracking`.

- Add `job_requirements.current_work_focus TEXT NULL`, with no default or backfill.
- Add `ck_job_work_focus` restricting non-null values to the seven approved codes.
- Advance Alembic's revision ledger.
- No new tables, indexes, relationships, data conversion or business-record UPDATE.
- Downgrade removes only the new check and column; saved focus would be lost.

The [generated SQL](../outputs/stage-2/0003_jd_work_focus.sql) was inspected. It contains
only those two ALTER TABLE statements and the Alembic ledger UPDATE in a transaction.
Neither company table, staff/recruiter assignments, criteria, ATS JSON, pgvector,
roles nor authentication settings are modified by this migration.

**Deployment dependency:** the updated ORM requires revision 0003. Do not restart or
deploy this code against Windows revision 0002 before an approved migration. The
Windows-backed server was not restarted as part of this task. The isolated preview
runs the new schema and code together. The additive ALTER requires a table lock;
use a fresh backup and bounded lock timeout when separately approved to apply it.

## Changed files

| File | Purpose |
| --- | --- |
| `src/jobmitra/modules/jobs/focus.py` | Stable focus codes, ordered labels and model check expression. |
| `src/jobmitra/modules/jobs/models.py` | Nullable mapped focus column and CHECK constraint. |
| `src/jobmitra/modules/jobs/schemas.py` | `WorkFocusPatch` validation/clearing and `JobRead` field. |
| `src/jobmitra/modules/jobs/service.py` | Atomic focus action using existing audit/version helpers. |
| `src/jobmitra/modules/jobs/router.py` | PATCH route and tracker labels in workspace context. |
| `src/jobmitra/templates/stage2/process_tracker.html` | Shared tracker and Change Focus form. |
| `src/jobmitra/templates/stage2/workspace.html` | Tracker placement, readable History, honest disconnected Pipeline. |
| `src/jobmitra/static/stage2/workflow.css` | Exact red branding, connected steps, horizontal scrolling, compact controls. |
| `migrations/versions/0003_jd_work_focus.py` | New additive migration, leaving applied revisions unchanged. |
| `outputs/stage-2/0003_jd_work_focus.sql` | Offline SQL for review. |
| `tests/test_stage2.py` | Focus/History/validation/conflict/rollback/preservation checks; current-head and Pipeline text assertions. |
| `scripts/test_stage2_isolated.py` | Optional `--pytest-args` to run only selected checks. |
| `README.md`, `docs/stage-2-schema.md`, this document | Pending schema change and review instructions. |
| `outputs/stage-2/tracker-preview.json`, `outputs/stage-2/tracker-validation.json` | Isolated preview location and verification summary; no credentials. |
| `output/playwright/jd-tracker-*.png` | Desktop, mobile and History review screenshots. |

No new dependencies or JavaScript behavior were needed. The existing generic form
handler supplies staff/version, submits JSON and reloads after saving. Company
Management application code and assets were not changed.

## Focused verification

```sh
.venv/bin/python scripts/test_stage2_isolated.py --pytest-args tests/test_stage2.py \
  -k 'work_focus or additive_migration_roundtrip or pages_fragments'
node --test tests/company-search.test.mjs
.venv/bin/ruff check src/jobmitra/modules/jobs tests/test_stage2.py \
  scripts/test_stage2_isolated.py migrations/versions/0003_jd_work_focus.py
```

- **10 passed, 43 deselected, 2.00 seconds**, in disposable PostgreSQL 18 with a
  private Unix socket and TCP disabled. No Windows test writes. One existing
  Starlette/httpx deprecation warning; no new dependency added to address it.
- **6 Company Directory search checks passed**. The focused workspace check also
  read the Company Directory successfully and verified company rows were unchanged.
- **Ruff passed.** No unrelated full regression run.
- Migration checks cover populated preexisting staff/JD rows, nullable focus on
  upgrade, invalid values rejected by PostgreSQL, downgrade/upgrade, unchanged
  company data and ORM-to-migration metadata comparison.
- API checks cover all seven codes, ordering/labels, clear/empty focus, no-op changes,
  exactly one useful event, persisted reload, independent fields, stale 409,
  audit-failure rollback, unsupported/legacy codes rejected without writes.
- Browser: saved Candidate Contact through the real form; reload retained it and
  History showed exactly one “Focus not set → Candidate Contact” event. All five
  tabs retained the tracker; Edit JD and the three expanding controls worked.
- Desktop **1440 × 1000**, mobile **390 × 844**: no page overflow. On mobile the
  tracker viewport is 328 px with an 850 px internally scrollable strip. Only one
  step is highlighted, with computed red `rgb(221, 0, 0)`.

An initial test assumed the newest audit row would always sort first in a shared
outer test transaction. Equal transaction timestamps made that assumption invalid;
the test now identifies the new event by its ID. Application behavior needed no fix.

## Review locally

The current disposable preview is at
<http://127.0.0.1:8765/requirements/e66f793f-2d32-4cf8-866d-4cb2553c17f5>.
It contains only synthetic preview records, clearly marked in the page banner.
Choose Preview Employee in Recording as, change or clear focus, then check History.
Switch tabs and narrow the browser; the tracker remains outside the tab panels.

If the preview has stopped, start a fresh empty isolated instance:

```sh
.venv/bin/python scripts/test_stage2_isolated.py --serve
```

Create a synthetic company in Companies, a staff member in Staff and a JD in
Requirements. Do not use Windows-backed port 8000 for this migration preview.
Stopping the preview discards its database and invalidates the prior JD URL.

Screenshots: [desktop](../output/playwright/jd-tracker-desktop.png),
[mobile full page](../output/playwright/jd-tracker-mobile-full.png),
[mobile viewport](../output/playwright/jd-tracker-mobile.png),
[History](../output/playwright/jd-tracker-history.png).

Next step requires separate user approval: apply **only `0003_jd_work_focus`** to
Windows `192.168.1.51:5432/jobmitra_dev`, then restart the Windows-backed app.

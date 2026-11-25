# Historical stage visibility and actions

## Cause and correction

The clean pipeline defaulted non-pool stages to `At this stage`, hiding advanced
candidates despite cumulative workflow counts. Email then resolved the current
membership stage, and the feedback service always recorded at the current stage.
Raw `ROUND` event references also lost their stable round identity after a
rejection, incorrectly removing rejected candidates from that round's reached list.

All non-pool cards now default to `All reached`. `At this stage`, selected/joined
and closed filters remain available. Candidate Pool keeps Find Candidates and
In this JD. Existing cumulative reach/awaiting calculations remain in use; the
round resolver now receives retained round IDs from event snapshots/payloads,
including after a rename or rejection.

Rows show the actual current stage. Successfully advanced/completed stages are
green `Stage completed`; current pending candidates are yellow; Not Selected,
Not Joined and cancelled selections remain distinct red outcomes. Pending rows
sort first, completed rows next and closed rows last. Previous stages provide
Profile, applicable Email and Feedback, with no Next Stage/rejection/joining
actions. Current-stage transitions retain their existing service and safeguards.

Feedback displays only the selected stage's notes, with retained stage history
available in the existing confirmation. Rejection snapshots remain visible.

## Compatible API extension — no migration

- `GET /api/v12/email-context`: optional `selected_stage` and
  `selected_round_id`. Without them, existing current-stage behavior remains.
- The response's `stage`/`round_id` describe the validated requested context;
  `current_stage`, `current_round_id` and `historical_context` retain the actual
  current membership facts separately.
- `POST /api/ats-v2/jobs/{job_id}/candidates/{link_id}/feedback`: optional
  `stage_code` and `round_id`. Omitting them retains the legacy current-stage
  feedback contract and idempotency fingerprints.
- The membership must belong to the JD; interview IDs must belong to that JD
  and be supported by its current membership or retained journey. Unreached,
  invalid or cross-JD targets are rejected. The four standard steps use the
  existing cumulative progression inference, without creating attendance events.
- New feedback appends one `FEEDBACK` event. Its from/to stages, label snapshot
  and existing `payload_json.feedback_stage` store the selected stage/round.
  No old event, membership, eligibility, stage, selection or rejection is updated.
- Interview feedback without sufficient retained round-ID evidence fails closed
  rather than being silently attached to the current round.
- Existing Contact/Screening, Company Submission and custom interview Email
  mappings are reused. Context responses that do not verify the requested stage
  fail instead of silently substituting the current stage. No template wording,
  delivery infrastructure or automatic sending was introduced.

## Changed files in the fix checkpoint

- `scripts/build_approved_v12.mjs`
- `scripts/v12-adapters/jobs.js`
- `src/jobmitra/modules/ats_v2/jobs.py`
- `src/jobmitra/modules/ats_v2/schemas.py`
- `src/jobmitra/modules/ats_v2/unified.py`
- `src/jobmitra/modules/ats_v2/unified_router.py`
- `src/jobmitra/static/ats_v2/approved-api.mjs`
- `src/jobmitra/static/ats_v2/approved.mjs` (generated)
- `src/jobmitra/static/ats_v2/jd-clean.mjs`
- `src/jobmitra/static/ats_v2/pipeline-email.mjs`
- `tests/test_historical_stage_actions.py`
- `tests/test_historical_stage_actions.test.mjs`
- This document.

The pending independent Email workspace was preserved separately before this
fix and is excluded from this checkpoint. Existing reference HTML, Companies/
Candidate Desk markup, Email Studio templates and fixed 138 × 114px card CSS
remain unchanged. No database schema, production record or Windows configuration
changed. Verification writes used only synthetic records in the Unix-socket-only
local PostgreSQL preview; SQLite checks use disposable files.

## Focused verification — 25 November 2026

20 Python checks passed: new historical feedback/email tests on PostgreSQL and
SQLite, existing pipeline Email contexts, legacy feedback rollback and
selection/joining/closure regressions. 24 JavaScript checks passed, including
generated cumulative helpers retaining rejected round IDs after renaming.
Ruff, syntax, whitespace and generated-source checks passed; no full suite ran.

Browser/API read-back:

- Contact -> Screening retains the candidate in Contact under All reached;
  At this stage excludes it. Counts remain cumulative, with no historical Next
  Stage/rejection action.
- The matching before/after view changes from 0 visible candidates to 5:
  3 completed and 2 rejected, without changing that JD's existing records.
- Contact Email uses the existing screening communication; historical Company
  Submission uses `candidate_submission`; historical Round 1 uses `custom_round`
  and Round 1's name even when the membership is in Round 2.
- Historical Contact feedback has from/to `CONTACT` while the membership stays
  `SCREENING`. Round 1 feedback carries Round 1's stable ID while the membership
  remains in Round 2. Existing events are checked byte/field-identical in fixtures.
- A rejected Round 1 member remains visible, reached count stays 2, rejection
  evidence remains, and adding historical notes does not reopen it.
- Candidate Pool search/direct attachment preserves the query, creates a POOL
  membership and disables Already added after canonical read-back.
- Card dimensions remain identical; no password/Unlock prompts or console errors.

Screenshots are ignored local review artifacts:

| Evidence | Project-relative path |
| --- | --- |
| Before | `output/playwright/historical-stage-before.png` |
| After | `output/playwright/historical-stage-after.png` |
| Historical Contact feedback | `output/playwright/historical-contact-feedback.png` |
| Current/completed round actions | `output/playwright/historical-round-actions.png` |
| Retained rejected round | `output/playwright/historical-round-rejected-preserved.png` |

Native Windows browser verification remains a deployment check. This task
creates only the requested local fix checkpoint; it does not push to GitHub.

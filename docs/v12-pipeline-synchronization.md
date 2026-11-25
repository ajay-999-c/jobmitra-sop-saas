# JD Pipeline progression and history synchronization

## Reproduction and comparison

Reviewed against the pre-clean-JD checkpoint `f3f801a^`, the clean redesign
`f3f801a`, historical-stage fix `5873356`, and Email workspace `035831c`.
The working canonical attachment route, `jobs.associate()`, PostgreSQL triggers,
membership IDs and stage-transition services were retained throughout.

Three frontend problems were reproduced before correction:

1. **Find Candidates hid membership actions.** Its new sourcing table rendered
   only Profile and a disabled Already added control after attachment. The same
   current Pool candidate had Next Stage in In this JD, but not in Find Candidates.
   The pre-redesign pipeline used its recruitment-action table instead of a
   separate sourcing-only action column. Both clean views now use one existing
   membership-action renderer. A current Pool membership offers Next Stage to
   Contact immediately, while historical/closed memberships cannot advance.
2. **An older state response could erase a newer browser projection.** A controlled
   delayed GET reproduced this around an actual PostgreSQL attachment: JD History
   was present after the committed write, then disappeared when the older response
   arrived. Direct pipeline read-back still contained the membership. The shared
   refresh implementation predates the redesign; it previously published every
   response regardless of request order. Only the latest refresh now publishes
   state. Superseded callers await that refresh; a newer failure is propagated,
   rather than reported as success with obsolete data.
3. **Open full JD history selected Overview.** The explicit Candidate Details
   shortcut used a generic profile handler hardcoded to Overview. This also
   predates the redesign. Its existing button now requests the History section;
   generic Profile shortcuts retain Overview. No profile layout changed.

The ordinary In this JD attachment/progression path worked during baseline
reproduction. No missing membership or corrupt stage was found in the synthetic
baseline. These reproductions establish display/synchronization failures, not
proof that a particular inaccessible office record has the same cause.

## Scope and preserved behavior

Both entry points still call `native.addToPool()` and
`POST /api/ats-v2/jobs/{job_id}/candidates`, followed by authoritative state
refresh. Existing server transactions create the Pool membership, ADDED event
and retry receipt together. No parallel frontend pool, invented event, migration,
record repair or automatic advancement was introduced.

Next destinations continue to come from canonical `next_stage`/`next_round_id`.
No custom round is hardcoded. Current actions, workflow/version checks, stale
stage checks, duplicate prevention, candidate eligibility and outcomes retain
their existing service handlers. All reached remains the default; completed,
pending and closed status colors, historical Email/Feedback and fixed card CSS
are unchanged. The transition success message now refers to server read-back
instead of incorrectly naming SQLite.

The independent Email workspace, approved composers/wording, Foundit parser,
registration, Companies, document security, Windows/NSSM configuration and
PostgreSQL schemas are unchanged. Original approved V12, clean-JD and proposal
HTML SHA-256 values remain unchanged.

## Verification — 25 November 2026

All writes used synthetic records in a fresh Unix-socket-only local PostgreSQL
cluster, schema `jobmitra_v12_dev_pipeline_regression`, preview port 8898.
Unit-test fixtures create separate disposable schemas or SQLite files.

- **19 Python checks passed:** four new API/transaction tests, four existing
  sourcing checks, seven historical-stage checks and four selection/closure/
  rollback checks. Unknown, Direct and Configured workflows were exercised.
- **35 JavaScript checks passed:** refresh ordering/failure propagation, the
  actual generated history handler, shared membership actions, allocation,
  historical stage rules, Email contexts and clipboard behavior.
- Ruff, Python/Node syntax, Git whitespace and generated-source checks passed.
  No complete suite was run.

Browser verification and direct PostgreSQL read-back:

| Workflow | Result |
| --- | --- |
| Pipeline attachment | One membership at Pool, immediately present in Find Candidates, In this JD and Candidate Profile JD History |
| Older-response race | Reproduced history disappearance before fix; same delayed-response test retains membership/history after fix |
| Pool -> Contact | Next Stage works directly from Find Candidates; candidate remains green/completed in historical Pool without transition controls |
| Full progression | Contact -> Screening -> Submission -> all three configured rounds -> Selected -> Joined through original UI handlers |
| Feedback / Email | Contact feedback persists at Contact; approved screening composer receives correct candidate/JD context |
| Interview | Scheduling persists as an INTERVIEW activity; no invitation is sent |
| Joining / eligibility | Confirmed joining records evidence; canonical eligibility is PLACED_LOCKED and another JD cannot allocate the candidate |
| Candidate Desk attachment | Original Add to JD Pool creates one equivalent membership and ADDED event; JD Participation, full JD History, JD Pools and JD Activity update without reload |
| Unconfirmed company rounds | Candidate Desk membership still advances from Pool to Contact; no invented company interview plan |
| Browser reload | Persisted membership, history and outcomes survive reload; explicit history shortcut opens JD History |
| Duplication / rollback | Same request key returns one membership; new duplicate request is rejected; simulated receipt failure rolls back membership and audit event |
| Office LAN | Existing password-free policy used; no unlock/login/capability prompts |

Pipeline example: JD 1 / candidate 4294967305 / membership 9 ended JOINED with
one ADDED, six MOVED, one FEEDBACK, one COMPANY_SELECTED and one
JOINING_CONFIRMED event, plus one interview activity. Candidate Desk example:
JD 3 / candidate 4294967304 / membership 10 had one ADDED and advanced to Contact.
The local schema had zero event-to-membership candidate/JD ID mismatches.

An initial automated joining submission returned 422 and left the membership
Selected; the explicit required date/evidence submission then succeeded. No
validation was bypassed. Browser-selector/prompt automation retries did not
require application changes. Existing rejected/closed and historical behavior
also passed the focused regression checks.

Ignored local evidence includes:

- `output/playwright/pipeline-regression-before.png`
- `output/playwright/pipeline-regression-after.png`
- `output/playwright/pipeline-fixed-profile-history.yml`
- `output/playwright/pipeline-history-shortcut-fixed.yml`
- `output/playwright/pipeline-activity-verified.yml`

## Existing office records and limitations

Read-only office inspection was attempted against `192.168.1.51:5432`, database
`jobmitra_dev`, schema `jobmitra_v12_dev_20261123_integration`, using the existing
private configuration. It failed with **No route to host**. No office counts,
affected-record consistency or Windows runtime behavior can be confirmed from
this session. No production record, configuration or historical event changed.

When connectivity is restored, inspect membership/stage values, attachment
events, canonical history projections and reference mismatches in a read-only
transaction. Existing valid memberships need no data repair for these frontend
failures. If actual missing data is found, first capture verified backups and
present an ID-specific, idempotent reconciliation plan for separate approval.
Never rewrite immutable events or infer original attendance/timestamps. No
repair script or repair action is part of this fix. Native Windows validation
remains a deployment check; this checkpoint is local only until a push is requested.

## Files in this checkpoint

- `scripts/build_approved_v12.mjs`
- `scripts/v12-adapters/jobs.js`
- `src/jobmitra/static/ats_v2/approved-api.mjs`
- `src/jobmitra/static/ats_v2/approved.mjs` (generated)
- `src/jobmitra/static/ats_v2/jd-clean.mjs`
- `tests/test_pipeline_synchronization.py`
- `tests/test_pipeline_synchronization.test.mjs`
- This report.

# Email context and JD workflow improvements

All verification uses isolated development records. The office PostgreSQL endpoint
remains inaccessible to Python (`No route to host`); office verification is not claimed.
No live email is required or sent for this work. Gmail browser tests use a local stub.

## Checkpoint 1 — canonical interview email context

Root causes:

- The context API disclosed a candidate's JD company only at Selected/Joined;
  the composer independently redacted it from interview-round templates. Missing
  company values therefore became placeholders in Round 1/2 emails.
- Every custom-round shortcut used an invitation even when historical movement
  proved that the selected round was completed. Completion now uses the existing
  custom-round template ID, with the actual completed/next configured round names.
- Company-facing F2F greetings used the company name, not its contact. The adapter
  recognized only candidate submission as a company audience, losing F2F intent.
  Candidate/company/contact/recipient fields now stay distinct. The F2F sentence
  explicitly includes candidate, role, hiring company and date. The current renderer
  already used the candidate field in its main sentence; the reported office-specific
  swapped input could not be reproduced without office access. Canonical field checks
  now reject such a mismatch rather than copying or sending it.

Early screening confidentiality remains in place. Interview-stage context exposes
the selected JD's canonical company; it never uses the candidate's current employer.
Missing required fields and unresolved placeholders block Copy/Send. A company-facing
email uses the selected saved contact's name, or Hiring Team for an unknown recipient.
Changing JD/company/recipient context invalidates the cached draft key and retains
the existing unsaved-draft confirmation.

The original approved reference and embedded document remain immutable. A runtime
script adapter corrects only context/wording; source HTML/CSS, centered email tables,
fonts and logo bytes stay unchanged. Gmail's CID/logo/MIME construction is preserved;
only a pre-MIME unresolved-context check was added.

Verification: 60 focused Python checks plus three missing-context cases, 19 JavaScript
checks, and actual browser previews for custom completion, Round 1 and F2F. Browser
Preview, copied content and mocked Gmail HTML/plain MIME reconcile. Multiple-JD
company resolution is tested on disposable PostgreSQL. No schema migration.

Files: `src/jobmitra/modules/ats_v2/unified.py`,
`src/jobmitra/modules/email_studio/gmail_service.py`,
`src/jobmitra/static/ats_v2/email-context.mjs`,
`src/jobmitra/static/ats_v2/email-studio.mjs`,
`src/jobmitra/static/ats_v2/pipeline-email.mjs`,
`tests/test_email_context_fixes.py`, `tests/test_v12_pipeline_email.py`,
`tests/email-context.test.mjs`, and this document.

## Checkpoint 2 — atomic Add to JD

All native V12 Add to JD entry points use `/api/v12/approved/jobs/{id}/attach`.
One serialized transaction calls the existing canonical Pool-first association,
retains its ADDED event, then uses the canonical POOL → CONTACT transition. The
normal history marks Pool completed. A failure rolls back membership, events and
receipt together. Existing memberships return their actual current stage, even
on a fresh request key; they are never reset. The legacy association primitive and
legacy API retain their original Pool-first contract for compatibility.

The shared frontend adapter reads back the canonical membership and opens its
actual stage. The Candidate Pool's redundant In this JD toggle is removed; search
results retain existing-member actions and an Open current stage shortcut.

Verification: 42 focused Python checks including rollback, concurrency and legacy
compatibility; 11 JavaScript checks. Browser Add immediately opened Candidate
Contact, retained Pool reach, and showed no redundant toggle. Normal Next Stage
progression and opening the existing stage were checked using synthetic records.
No schema migration, automated email, feedback or appointment was introduced.

Files: `src/jobmitra/modules/ats_v2/jobs.py`,
`src/jobmitra/modules/ats_v2/approved_router.py`,
`src/jobmitra/static/ats_v2/approved-api.mjs`,
`src/jobmitra/static/ats_v2/jd-clean.mjs`, `scripts/build_approved_v12.mjs`,
`src/jobmitra/static/ats_v2/approved.mjs`, `tests/test_attach_contact.py`,
`tests/test_pipeline_synchronization.test.mjs`, and this document.

## Checkpoint 3 — direct forward stage movement

Move to Stage fetches the current membership/workflow and presents a searchable
list of valid later destinations, including stable custom-round IDs and ordering.
The confirmation lists intermediate completions. Next Stage remains unchanged.

One serialized transaction calls every existing canonical forward transition.
Those normal MOVED/outcome events drive the existing cumulative reach, completion
indicators and current-stage counts; no second status/counting system is added.
The existing request receipt also retains manual-confirmation metadata: previous
stage, destination, completed stages, actual recording timestamp, access policy
and null individual employee identity. No historical completion dates are invented.

Selection requires the actual selection date. Joining requires actual joining
date/evidence and preserves the existing date ordering, eligibility and placement
locks. Closed/rejected records cannot reopen; stale stages/workflow versions and
concurrent conflicts fail safely. Errors roll back the entire path. Replayed keys
return the existing result without repeating transitions. Unknown workflows cannot
invent company rounds or outcome destinations.

Verification: 34 focused Python cases (including attachment compatibility) across
SQLite and PostgreSQL, plus 13 JavaScript checks using the original cumulative
helpers. Browser Contact → Portfolio Assessment → Owner Discussion recorded each
intermediate normal movement exactly once. Counts, completed indicators and both
JD histories survived reload; the other JD remained at Screening. The membership
had one ADDED event, six MOVED events, zero activities and two manual receipts.
Mobile checks verified required selection/joining inputs without submitting an
outcome. No email, feedback, appointment or meeting link was generated.

New files: `src/jobmitra/modules/ats_v2/direct_movement.py`,
`src/jobmitra/static/ats_v2/direct-movement.mjs`,
`src/jobmitra/static/ats_v2/searchable-select.mjs`,
`tests/test_direct_movement.py`, `tests/direct-movement.test.mjs`.
Updated files: `src/jobmitra/modules/ats_v2/approved_router.py`,
`src/jobmitra/modules/ats_v2/request_receipts.py`,
`src/jobmitra/static/ats_v2/jd-clean.mjs`, and this document. No schema migration.

## Checkpoint 4 — searchable selectors and Candidate Pool

The existing company selector in JD Create/Edit, requirement picker, Candidate
Desk Add to JD selector and JD Pools picker now share the progressive searchable
select component. Their original option sets, canonical values, change handlers,
active-company/active-JD rules and business validation remain in place. Matching
is trimmed, case-insensitive and partial; JD search also includes its canonical
reference and hiring company. Arrow keys, Enter, Escape and clear no-results
feedback are supported. Typing an unmatched query cannot submit a previously
selected company/JD. JD field errors focus the visible company search control.

These option sets come from the complete canonical bootstrap collections, not a
paginated dashboard page. No request is made for each company/JD keystroke.
Candidate Pool retains its single existing search field and server-side pagination
across the whole database. Its opt-in identity lookup now includes partial email
addresses as well as the existing name/mobile/professional evidence. Ordinary
professional search does not gain identity matching implicitly. Debouncing
invalidates old responses immediately, including during the debounce interval;
re-rendering preserves search focus/cursor. No browser persistence is added.

Verification: six focused Python cases on disposable SQLite/PostgreSQL, including
an older target outside the first ten results; 20 focused JavaScript checks cover
matching, request races, form recovery and existing pipeline synchronization.
Browser checks used 1440×1080 desktop and 390×844 mobile viewports. Company selection
changed between two real fixture UUIDs; an unmatched query produced zero POSTs,
then the corrected form created synthetic JD 3 and API read-back confirmed its
company UUID. The new Draft JD remained absent from active-only Add to JD and
JD Pools selectors. An existing membership opened Owner Discussion without a
write/reset. Partial email/mobile queries found the correct candidate. An actual
older search response was deliberately delayed until after the newer result;
it could not replace that result. The Pool still had exactly one search field.
No new JavaScript/API errors occurred in the verified operations.

The updated attachment help text also describes its actual initial Contact
transition rather than the obsolete prototype Pool-only behavior. This is wording
only; attachment service semantics are unchanged from checkpoint 2.

Files: `scripts/build_approved_v12.mjs`,
`src/jobmitra/modules/ats_v2/candidates.py`,
`src/jobmitra/static/ats_v2/approved.mjs`,
`src/jobmitra/static/ats_v2/creation-forms.mjs`,
`src/jobmitra/static/ats_v2/jd-clean.mjs`,
`src/jobmitra/static/ats_v2/searchable-select.mjs`,
`src/jobmitra/static/ats_v2/search-request.mjs`,
`src/jobmitra/static/ats_v2/workspace-selectors.mjs`,
`tests/test_clean_jd.py`, `tests/searchable-selectors.test.mjs`, and this document.

## Local evidence and preservation

Screenshots are private local artifacts under
`output/playwright/workflow-improvements/` and are intentionally excluded from Git:

- `custom-round-email.png`, `round1-email.png`, `f2f-email.png` — corrected previews.
- `attached-contact.png` — immediate Contact with Pool reach retained.
- `direct-stage-confirmation.png`, `direct-first-round.png`,
  `direct-custom-rounds.png`, `completion-after-reload.png`,
  `candidate-jd-history.png`, `direct-stage-mobile.png` — direct movement/history.
- `company-selector.png`, `company-selector-mobile.png`,
  `jd-search-selected.png`, `add-jd-selector.png`,
  `pool-jd-selector-mobile.png`, `candidate-email-search.png`,
  `candidate-search-mobile.png` — selectors and full-database candidate lookup.

Final isolated browser fixture: 2 synthetic candidates, 2 synthetic companies,
3 JDs, 4 memberships, zero candidate activities. Atomic Contact Demo remains at
Owner Discussion in JD 1 and Screening in JD 2; JD 1 has one ADDED, six MOVED and
three request receipts (attachment plus two direct confirmations). The only two
EMAIL_SEND events are the attempt/result for the single mocked composer send.
All fixture foreign keys remain validated. No office records were changed.

For JD 1 the normal reached/awaiting counts after reload are:

| Stage | Reached | Awaiting |
| --- | ---: | ---: |
| Pool | 2 | 0 |
| Contact | 2 | 0 |
| Screening | 2 | 0 |
| Company Submission | 2 | 0 |
| Portfolio Assessment | 2 | 0 |
| Manager Discussion | 2 | 1 |
| Owner Discussion | 1 | 1 |
| Selected | 0 | 0 |
| Joined | 0 | 0 |

There are no database schema changes. Proposal renderer/storage, resume storage,
registration and paste parsers, Windows configuration, OAuth handling, CID logo
embedding and Email Studio source templates are unchanged. Office LAN mutation
checks use the existing password-free policy on disposable PostgreSQL fixtures;
production sending remains disabled. The approved HTML still has SHA-256
`a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e`.
Generator consistency, focused Ruff/syntax and Git whitespace checks pass. Existing
checkpoint 1–3 verification is reused; the full suite is not rerun. Native Windows
and the inaccessible office PostgreSQL database are not claimed as verified.

## Office PostgreSQL connectivity retest after the four checkpoints

The supplemental connection request was attempted using the existing private
`.env` credentials plus the `.env.v12.mac.postgres` settings overlay; neither file
was changed. The overlay alone intentionally omits credentials. Effective target:
`192.168.1.51:5432`, database `jobmitra_dev`, schema
`jobmitra_v12_dev_20261123_integration`, PostgreSQL backend, explicit development
flags and previously approved trusted-private-LAN mode. Configuration validation
passes; this is not proof of remote schema/application compatibility.

| Probe | Result |
| --- | --- |
| Sandboxed Python TCP | PermissionError, errno 1: Operation not permitted |
| Escalated native `nc` | TCP connection to port 5432 succeeded |
| Escalated Python TCP using the effective settings | OSError, errno 65: No route to host, before authentication |
| Escalated native `psql` with private credentials passed only through its environment | Exit 2: No route to host, before authentication |

The supported sandbox escalation was used. TCP reachability exists for native
`nc`, but the application interpreter and `psql` still cannot establish a socket
from this agent session. The sandbox initially blocks access; the remaining
process-specific network restriction cannot be attributed conclusively to a
particular macOS privacy/firewall policy from this evidence. No authentication
rejection, database SQLSTATE or schema-compatibility result was obtained. Do not
change database passwords, server authentication or firewall settings on this
basis.

No remote read-back, remote test schema creation or remote write tests were
performed. The existing SQLite/local PostgreSQL verification above remains valid
and is explicitly separate from office verification. Before remote functional
testing, authenticated connectivity from the application interpreter must succeed;
then inspect the office schema read-only and provision a separately named empty
development schema for synthetic records using the existing provisioning tool.
Never point mutation tests at the office integration schema or clone confidential
records unnecessarily. No GitHub push was made.

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

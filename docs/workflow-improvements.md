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

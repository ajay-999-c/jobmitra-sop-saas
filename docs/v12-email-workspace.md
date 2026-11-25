# V12 independent Email workspace and branded proposal email

## Approved sources and root cause

The approved branded proposal email is `Jobmitra_Company_Proposal_Final.html`
(commit history: `bab7492`, after the original Email integration). It contains
the existing `makeEmail()` renderer, Jobmitra logo, red theme, fixed subject,
greeting, body, Vishal Agrawal signature and company footer. Its SHA-256 remains
`dea48915cb087db892d6030d4ffd92739ccc3986ad79a1b9bb39e3ea5017750c`.

The PDF workflow previously displayed `proposal_documents.email()` as a plain
textarea. The UI now uses the approved branded renderer, resolving the selected
company/proposal through the existing guarded APIs. The legacy JSON API remains
compatible; the PDF renderer, terms, storage, signatures and status services
are unchanged.

Candidate/JD email uses the existing V12 `EMAIL_STUDIO_DOCUMENT` registry from
the immutable approved V12 HTML. The independent workspace and contextual
shortcuts use that same document and rendering logic. Its original wording,
validation and template content are unchanged; a runtime bridge exposes its
existing validation for the HTTP-compatible copy adapter. Company proposal
email loads the original `/email/proposal` document without changing it or
weakening the proposal workspace CSP.

The landing page reuses `templates/email_studio/index.html` content and its
existing scoped `portal.css` rules. Legacy `/email/updates`, `/email/submission`
and `/email/proposal` responses remain byte-identical to their approved files.

## Routes and available templates

- `/workspace-v12/email`: original Email landing choices in the approved V12 shell.
- `/workspace-v12/email?tool=updates`: full existing candidate/JD composer.
- `/workspace-v12/email?tool=submission`: same composer, Company Submission selected.
- `/workspace-v12/email?tool=proposal`: original standalone Company Proposal composer.

The four primary buttons are Companies, Candidate Desk, JD Tracking and Email,
in that order. The new button uses the unchanged shared header styles.

| Registry key | Existing template |
| --- | --- |
| `jobmitra_screening` | Jobmitra Screening · Invitation |
| `screening_completed` | Screening Completed · Feedback Pending |
| `screening_cleared` | Screening Cleared |
| `interview_scheduled` | Company Interview · Scheduled |
| `technical_interview` | Technical Interview · Scheduled |
| `custom_round` | Custom Company Interview Round |
| `round1_completed` | Round 1 · Completed |
| `round1_cleared` | Round 1 · Cleared |
| `round2_completed` | Round 2 · Completed |
| `round2_cleared` | Round 2 · Cleared |
| `final_completed` | Final / Senior Management Interview |
| `selected` | Selected by Hiring Company |
| `offer_received` | Offer Shared / Received |
| `joined` | Joined Successfully |
| `not_selected` | Not Selected · Candidate Application Update |
| `candidate_submission` | Candidate Submission · Profiles to Company |
| `f2f_company` | F2F Interview · Confirmation to Company |
| Original proposal document | Company Proposal · Recruitment Services Proposal & Terms of Engagement |

All 17 registry templates remain selectable independently; Company Proposal is
the eighteenth email type, using its existing separate approved renderer.
The older standalone Candidate Updates/Submission tools remain available at
their unchanged legacy document endpoints.

## Context, drafts and attachments

Pipeline and JD History resolve canonical candidate/JD membership using the
existing `/api/v12/email-context` service. Historical pipeline actions preserve
the validated selected stage and stable interview round ID from the historical
stage fix. Contextual draft keys also include the selected stage, so Contact and
Screening do not share a cached draft merely because they use the same template.
Batch submission retains company
contacts and candidate IDs. Candidate Profile now has an Email shortcut;
JD History has an Email action beside Open JD pipeline. These shortcuts were
absent from the current V12 profile implementation. A single membership resolves
its canonical stage; a profile with no unique JD opens a labelled manual draft
with canonical candidate details, without inventing a JD or recorded outcome.

Prepare Email resolves the selected saved proposal and recipient using
`/api/v12/approved/companies/{company_id}/proposals/{proposal_id}/email`.
The approved subject remains
`Jobmitra.com | Recruitment Services Proposal & Terms of Engagement`.
Company/contact, recipient, reference and fee are populated in the composer;
the greeting uses the recorded contact where available. The approved email
body/signature/footer are unchanged. Reference/fee are composer metadata,
not unapproved additions to the original email wording.

Contextual proposal download points to the selected preserved 6% or 8.33% PDF.
It replaces the legacy Word download control only in that contextual composer.
There is no automatic attachment, delivery or Sent/Accepted status update.
The independent manual proposal tool retains its original 8.33% Word download;
use Companies → Prepare Proposal for saved 6%/8.33% PDF versions.

Drafts remain in memory when switching workspaces, tools or closing a contextual
composer. Changing a contextual draft asks before replacing edited fields;
cancelling preserves the draft. Browser reload/exit uses the normal unsaved-edit
warning. No new login/capability prompt, browser persistence, email transport,
database table or migration was introduced.

The prior Email tools had no persistent email draft/history service. This change
preserves their copy/download behavior and existing proposal/recruitment history;
it does not claim to save a sent email or create new durable email history.

## Files changed

- `scripts/build_approved_v12.mjs`
- `scripts/v12-email.mjs`
- `src/jobmitra/modules/ats_v2/unified_router.py`
- `src/jobmitra/static/ats_v2/approved.mjs` (generated)
- `src/jobmitra/static/ats_v2/email-studio.mjs`
- `src/jobmitra/static/ats_v2/email-workspace.css` (generated)
- `src/jobmitra/static/ats_v2/proposal-workflow.mjs`
- `src/jobmitra/static/ats_v2/v12-shell.mjs`
- `src/jobmitra/static/ats_v2/v12-shell.css`
- `src/jobmitra/templates/v12/approved.html` (generated)
- `src/jobmitra/templates/v12/proposal.html`
- `tests/test_v12_startup_proposal.py`
- `tests/test_v12_email_workspace.py`
- `tests/email-workspace-copy.test.mjs`
- This document.

## Verification — 25 November 2026

Preview: `http://127.0.0.1:8894/workspace-v12/email`.
It uses a Unix-socket-only local PostgreSQL instance and the disposable
`jobmitra_v12_dev_cleanjd_preview3` schema. Nimar Motors was read from the earlier
isolated proposal-test instance and copied into this local schema. No test
proposal was inserted into an active office or remote source schema.

| Check | Result |
| --- | --- |
| Four buttons, order, matching styles | PASS; mobile buttons all 36px high, padding 9px 8px; document width 390px at 390px viewport |
| Direct URL, refresh, back/forward | PASS for independent Email/tool routes inside V12 |
| Complete registry | PASS: 17 original V12 options plus original branded proposal tool |
| Independent manual composition | PASS: no candidate/JD IDs required; editable fields, subject and preview |
| Branding and approved wording | PASS: original logo, subject, greeting structure, HTML body, signature and footer |
| Nimar Motors 6% and 8.33% | PASS: both created through the existing UI in the disposable local copy; correct company/contact/recipient/reference/PDF option |
| Proposal metadata, history and downloads | PASS: two preserved PDFs, SHA-256/size verified; downloaded 8.33% bytes equal stored bytes; 10 clauses each; zero status events |
| Pipeline, Profile and JD History | PASS: joined candidate resolves correct job/template; missing candidate email is clear |
| Batch submission | PASS: company recipient, job and selected candidate context retained |
| Profile without a JD | PASS: canonical candidate details and explicit manual-context notice |
| HTTP clipboard | PASS: secure Clipboard API disabled in browser; actual copy writes contain correct subject and distinct HTML/plain body for candidate and proposal composers |
| Unsaved edits | PASS: workspace switch/back-forward retains draft; cancelling another context preserves edited subject/candidate |
| Missing recipient | PASS: standalone proposal has empty recipient with explicit guidance; no fabricated address |
| Office LAN / no delivery | PASS under existing policy; no password prompts, send operation or status change |
| Browser console | PASS: zero errors/warnings in both verification sessions |

26 focused Python tests passed, followed by 3 final route/source-preservation
checks (2 repeats plus the approved-source test). 24 focused JavaScript checks
passed. Generated-source equality, Node syntax, Python/Ruff and whitespace
checks passed. No full suite was run. Native Windows browser/NSSM validation
remains a deployment check; the HTTP clipboard fallback was exercised on Mac.

Both approved HTML references and all three original standalone Email files
remain byte-identical to the verified Git checkpoint. Clean JD source/card CSS,
PDF renderer, terms, storage and security code remain unchanged. No production
records, configuration, NSSM service or Git commit/index/remote was modified.

Screenshots (ignored local review artifacts):

- `output/playwright/v12-four-workspace-navigation.png`
- `output/playwright/v12-independent-email-studio.png`
- `output/playwright/v12-company-proposal-email-branded.png`
- `output/playwright/v12-email-mobile-navigation.png`

## Final release review — 25 November 2026

The clean JD checkpoint (`f3f801a`), historical-stage fix (`5873356`), Windows
deployment guide (`d993ec4`) and document-storage diagnostics (`e1096d0`,
`0ac017f`) were already committed; this addition does not duplicate them.

After merging the historical-stage fix, 9 focused Python checks passed for
Email routes, original-source preservation and startup compatibility. 24
JavaScript checks passed for copying, historical-stage contexts and pipeline
Email, including distinct draft keys for historical stages using one template.
Ruff, syntax, whitespace and generated-source consistency checks passed.

The current preview on port 8898 uses the same disposable local PostgreSQL
schema described above. All four primary workspace tabs were rechecked in the
browser. Candidate Contact still defaults to All reached, retains completed and
rejected candidates, and opens the original screening composer with the correct
canonical candidate/JD context. The saved Nimar Motors 6% proposal opens its
original branded Email composer with the correct contact, recipient, reference
and preserved PDF download. No new proposal, recruitment event or status was
created during this release review. The earlier isolated 6%/8.33%, clipboard,
draft-preservation and desktop/mobile verification results remain applicable.

No new dependencies, private ENV files, runtime evidence, database files or
documents are included. The immutable HTML sources, Companies/Candidate Desk
design, PDF renderer, Office LAN authorization and Windows storage protections
remain unchanged. Native Windows/NSSM browser confirmation remains pending.

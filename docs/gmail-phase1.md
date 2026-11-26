# Gmail — Mac development modes

Gmail is disabled by default. Both modes require the explicit Mac loopback V12
development profile and `gmail.send` authorization. Test mode retains the existing
**Pooja Jobmitra** sample restriction. Live mode resolves each selected candidate’s
registered email from the canonical database. Windows and Office LAN sending remain
refused; a shared network or declared name is never a verified employee identity.

## Configuration

Use a private environment file, never a tracked example with actual secrets:

```dotenv
JOBMITRA_GMAIL_ENABLED=true
JOBMITRA_GMAIL_SENDER=jobmitra@gmail.com
JOBMITRA_GMAIL_CREDENTIALS_FILE=/Users/mac/.config/jobmitra/gmail/gmail_credentials.json
JOBMITRA_GMAIL_TOKEN_FILE=/Users/mac/.config/jobmitra/gmail/gmail_token.json
JOBMITRA_GMAIL_MODE=test
JOBMITRA_GMAIL_TEST_RECIPIENT=pooja.jobmitra@gmail.com
JOBMITRA_GMAIL_TEST_JOB_IDS=
```

These extend the existing development database settings; they do not select,
create, migrate or copy a database. Enable `JOBMITRA_UNIFIED_V12_ENABLED`,
`JOBMITRA_ATS_V2_ENABLED`, and `JOBMITRA_UNIFIED_V12_LOCAL_DIRECT_EDITING`
only with the existing isolated development store. PostgreSQL additionally
requires its existing explicit development opt-in/schema checks. All local
document roots must remain under `runtime/`. Bind Uvicorn to `127.0.0.1`, with
`--no-proxy-headers`; Gmail also validates the actual peer, server and Host and
rejects forwarded headers. Never bind this profile to a LAN/public interface.

The Gmail directory must be owner-only mode **700**; both JSON files must be
owner-only regular files mode **600**, single-linked, outside the repository,
without symlink components. Credentials must be an installed-app OAuth client;
the token must match that client, use Google's token endpoint and list exactly
`https://www.googleapis.com/auth/gmail.send`. No inbox scopes are requested.
Never paste these JSON files, tokens or Google raw exceptions into reports.

The service uses a private sidecar lock, atomic replacement and fsync when
refreshing credentials. Refresh is serialized across threads/processes. Missing,
unsafe or revoked credentials produce a reconnect/unavailable status. Reauthorize
outside request handling using existing send-only authorization tooling; the app
never starts an interactive OAuth flow. “Gmail Connected” means the local token
is usable (refreshed if needed), not that delivery or sender ownership is proven.

## Actual candidate recipients — Mac live mode

In the explicitly authorized private Mac profile only:

```dotenv
JOBMITRA_GMAIL_ENABLED=true
JOBMITRA_GMAIL_MODE=live
```

Keep the existing sender, external private OAuth paths, V12 development flags,
local-direct-editing policy and loopback binding. Shared/example configuration
remains disabled, defaults to test mode, and does not enable Windows sending.
Do not enable this profile on a LAN bind or add forwarded-IP trust.

`GET /api/v12/gmail/context/{candidate_id}` retrieves the current canonical name
and validated registered email. It returns a mode/ID/name/address snapshot plus
the effective recipient. The composer checks this against its selected candidate,
populates a read-only registered-address field in live mode, removes the fixed test
banner and names the actual recipient in the explicit Send confirmation. Missing,
invalid or mismatched candidate details disable sending; update the candidate
profile and reopen its email instead of overriding the To field.

At send time the backend re-reads that same candidate inside the serialized claim
transaction, rejects changed names/addresses/snapshot IDs or altered recipients,
and constructs MIME with its own resolved address. The frontend cannot choose a
different To, CC or BCC. In live mode JD context must still be a real membership
with its canonical company; the synthetic-JD allowlist applies only to test mode.
Company-facing templates, proposals, attachments and bulk sends remain manual.

History records the actual recipient, candidate/JD IDs, delivery mode and Gmail
message/thread IDs. Live entries are labelled Email; old test entries remain Test
email. Duplicate claims, separate resend confirmation, conservative unknown results,
zero automatic retries, OAuth refresh locking and CID-logo MIME are preserved.
Opening profiles, registering/attaching candidates and stage movement never send.

Focused implementation checks: 86 Python cases passed (35 new plus 51 existing)
on disposable SQLite/local PostgreSQL, all with mocked Gmail. Twenty focused
JavaScript checks cover recipient switching, confirmation, context rejection,
existing templates/copy and history labels. A separate mocked browser preview
verified controls before enabling the private real transport.

The configured office PostgreSQL endpoint still fails before authentication with
`No route to host` after supported sandbox escalation. The user confirmed that the
existing Jobmitra test record in the running isolated PostgreSQL preview was the
candidate they created and explicitly authorized its use instead. No duplicate or
substitute record was created. The one controlled email used that canonical record,
its registered address and existing JD membership, via the actual browser Send and
recipient confirmation workflow. Gmail returned message/thread IDs, the user
confirmed receipt and correct branding, and history survived page reload. No email
was sent to Pooja during this feature. Before/after hashes of all candidates,
companies, JDs, rounds, memberships, resumes, activities and non-email recruitment
events match. Exactly one attempt/result pair was added; no resend occurred.

The existing Mac preview on port 8895 now uses the ignored, owner-only private
`.env.v12.gmail.mac` profile. It enables real Gmail only for that loopback instance;
other shared/example settings and Windows deployment configuration are unchanged.
To restart the same authorized profile while the existing local PostgreSQL cluster
is running, from the project root:

```sh
uv run --no-sync --env-file .env.v12.gmail.mac python -m uvicorn jobmitra.main:app --app-dir src --host 127.0.0.1 --port 8895 --workers 1 --no-access-log --no-proxy-headers
```

Private verification journals and screenshots remain excluded from Git. Live Gmail
IDs and candidate record identifiers are reported privately rather than embedded in
release documentation. Office database identity/compatibility and Windows sending
are not claimed as verified or enabled.

Additional reviewed files: `tests/test_gmail_live.py`, `tests/gmail-live.test.mjs`.
No dependencies, schema migrations, approved template bytes or Windows deployment
configuration change for this feature.

## Sending and scope (retained test mode)

Open the existing candidate profile or JD History Email shortcut. Review the
approved preview and To address, click **Send Email**, then confirm the effective
test recipient and subject. Copy Email remains available. An independent manual
draft without a canonical candidate cannot send; open its candidate shortcut.

Direct sending supports the existing candidate template IDs:
`jobmitra_screening`, `screening_completed`, `screening_cleared`,
`interview_scheduled`, `technical_interview`, `custom_round`, `round1_completed`,
`round1_cleared`, `round2_completed`, `round2_cleared`, `final_completed`,
`selected`, `offer_received`, `joined`, `not_selected`.

Company proposal, candidate submission and `f2f_company` (company/panel-facing)
remain manual/copy workflows. Candidate-facing face-to-face scheduling uses
`interview_scheduled` with its existing interview mode. No PDF/resume attachments,
bulk sends, schedules, stage-triggered sends or automatic follow-ups are added.

The backend checks the canonical sample candidate and intended address, restricts
the actual recipient, strips CC/BCC, rejects extra request fields and validates
HTML/subject. A JD must belong to the candidate and be explicitly listed in
`JOBMITRA_GMAIL_TEST_JOB_IDS` after review as synthetic/non-client context;
its company ID must match. Leave this list empty for candidate-only testing.
Never approve a real recruitment JD or paste real client details into a test draft.

The exact reviewed HTML and plain text form MIME alternatives. Only the approved
embedded Jobmitra logo is accepted as an inline image; it becomes a CID JPEG so
Gmail can display it without an external fetch. There are no document attachments.
Approved HTML source and template text remain unchanged.

## History and duplicate protection

No schema change is required. Existing immutable `recruitment_events` stores an
`EMAIL_SEND_ATTEMPT` before network I/O and an `EMAIL_SEND_RESULT` afterwards.
They share one UUID and collapse to **one logical email history entry** in the
candidate profile/JD journey. Metadata includes canonical IDs, template, intended
and actual addresses, subject, test flag, timestamps, Gmail IDs, sanitized result,
content fingerprint and null verified employee identity. Full bodies and OAuth
secrets are not persisted. Existing audit facts are never updated/deleted.

Serialized short transactions prevent duplicate claims on both supported database
adapters. Repeated references with different content conflict. Matching content
under a different reference returns its existing attempt. An intentional resend
requires a separate confirmation referencing the previous result; concurrent
resends of that parent still create only one new attempt.

Statuses are **Sending**, **Accepted by Gmail**, **Failed**, and
**Send outcome unknown**. Acceptance is not proof of delivery. Gmail POST uses
`users.messages.send(userId="me")`, zero API retries and a one-shot HTTPS
transport (including no hidden socket reconnect/retry). Network timeouts are 15s.
Lost/5xx responses remain unknown; no automatic resend occurs. A claim without
a result for two minutes is conservatively displayed as unknown after a crash
or failed result persistence. Do not retry it automatically; check the sender's
mailbox manually before explicitly confirming another send.

The controlled live acceptance test also requires manual confirmation of the
received From address, logo/layout and content when mailbox access is unavailable.
Automated tests mock Gmail; they must never use the real token or send real mail.

The one-shot transport requests an identity response and also safely decodes
bounded gzip/deflate responses. Without this decoding, Gmail could accept a
message while the JSON result was unreadable. An unknown result is always retained
honestly; receipt confirmation does not retroactively invent a Gmail API ID.

## Focused checks

```sh
JOBMITRA_GMAIL_ENABLED=false PYTHONPATH=src .venv/bin/python -m pytest tests/test_gmail_phase1.py -q
node --test tests/gmail-phase1.test.mjs
npm run check:v12
uv lock --check
```

Keep Gmail disabled in generic test process configuration; individual synthetic
fixtures explicitly opt in. Do not run live sending as part of the test suite.

## Reviewed implementation files

| Area | Files |
| --- | --- |
| Settings/dependencies | `.env.example`, `.gitignore`, `pyproject.toml`, `uv.lock`, `src/jobmitra/core/config.py` |
| App/router | `src/jobmitra/main.py`, `src/jobmitra/modules/email_studio/gmail_router.py` |
| OAuth, MIME, transport | `src/jobmitra/modules/email_studio/gmail_service.py` |
| Existing immutable history | `src/jobmitra/modules/email_studio/gmail_history.py` |
| Composer/context adapters | `src/jobmitra/static/ats_v2/gmail-send.mjs`, `src/jobmitra/static/ats_v2/email-studio.mjs`, `src/jobmitra/static/ats_v2/pipeline-email.mjs`, `src/jobmitra/static/ats_v2/approved-api.mjs` |
| Canonical generator/output | `scripts/build_approved_v12.mjs`, `src/jobmitra/static/ats_v2/approved.mjs` |
| Focused checks | `tests/test_gmail_phase1.py`, `tests/test_gmail_postgres.py`, `tests/gmail-phase1.test.mjs`, `tests/email-workspace-copy.test.mjs` |
| Documentation | `docs/gmail-phase1.md` |

## Mac verification checkpoint — 26 November 2026

- 60 focused Python checks passed, using synthetic SQLite and disposable local
  PostgreSQL schemas; all automated Gmail responses were mocked.
- 28 focused JavaScript checks passed. All 15 actual approved candidate template
  renderings also passed mocked dispatch, plain/HTML MIME and CID-logo checks.
- Desktop (1440×1080) and mobile (390×844) browser checks passed, including no
  mobile horizontal overflow and candidate history after reload.
- Ruff, syntax, lockfile, whitespace and generated-source checks passed. The
  approved HTML hash and embedded template bytes remain unchanged.
- The office PostgreSQL connection was unavailable to Python. The user approved
  using an existing demo candidate in isolated local PostgreSQL instead; this
  does not verify the original office candidate's identity.
- The first controlled test was received with correct sender/branding, confirmed
  by the user, but retained an unknown API outcome. A compressed-response regression
  was reproduced and fixed with mocks. The user explicitly approved one additional
  live test via separate Resend confirmation; it returned Gmail message/thread IDs
  and persisted acceptance once. There were no automatic resend attempts.
- Token refresh persisted securely with the send-only scope. Candidate/company/JD
  and membership hashes remained unchanged; no non-email recruitment events were
  added during the live test. No schema migration or office database write occurred.
- Private screenshots, message IDs, test journals, OAuth files and local launcher
  configuration remain outside tracked release files. No Windows deployment or
  production sending is enabled by this checkpoint.

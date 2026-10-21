# Stage 3 Candidate Desk — implementation review

Implemented against checkpoint **`d807fb9`**, branch **`main`**, on 2026-10-21.
No commit or push was made. Initial Git status contained only the two supplied,
untracked reference files; both were preserved unchanged. The UI reference used was
`Jobmitra_Stage3A_Candidate_Desk_UI_v5_Email (1).html`.

**Windows was not contacted or modified in this task.** No live DDL, migrations,
seeds, company/JD edits, role changes or external AI calls occurred. All database
writes were confined to disposable PostgreSQL 18 clusters; all document test writes
used temporary private directories and synthetic files.

## Working features

- Persistent Candidate Desk Today dashboard, searchable directory, candidate profile,
  add/edit dialog, Office Visits, independent Job Search Requests and Domain Catalog.
- Name/mobile required; optional validated/searchable email; free-text role suggestions;
  dependent domain/subdomain; qualification, skills, location preferences, hometown,
  the reference's 28 states and 8 UTs, and nullable relocation choice.
- Experience is explicitly entered/stored in **months**, rather than the prototype's
  fractional years, so there is no hidden conversion or rounding. Salary amounts
  remain decimal strings through the UI and NUMERIC in PostgreSQL; each has its own
  period/basis. Empty values stay missing; no inferred salary units or relocation.
- Live mobile duplicate lookup and a server-side check. Shared numbers are allowed
  only with explicit separate-person confirmation; advisory locking prevents two
  concurrent registrations bypassing that warning. No merge or unique-mobile rule.
- Walk-in creation includes exactly one initial visit atomically. Foundit registration
  creates neither a visit nor a search request by default. An explicitly selected
  initial search request joins the registration transaction. Repeat visits use the
  existing candidate UUID.
- Search requests have dynamic staff assignment, follow-up dates, next actions,
  independent statuses and computed overdue flags. “Placed” is staff-reported;
  no JD application, verified selection or match score is invented.
- Domain/subdomain Add, Rename, Deactivate; normalized duplicate names conflict.
  Stable keys/IDs survive renames; inactive referenced labels remain visible.
  No taxonomy was found or seeded. Domains represent function, not company industry.
- Original, modified and authority PDF/DOCX upload/download. Each immutable file has
  a version, byte size and SHA-256. Modified copies require an original from the same
  candidate and explicit accuracy/authorization acknowledgement. Authority uploads
  are labelled Unverified; visit signature observations remain separate.
- The highest original-resume version is the current original (a deterministic rule,
  no mutable current marker). Every older version remains downloadable. Manual
  ChatGPT/Claude JSON results retain their exact source document version, provider,
  optional model and separate employee-review state. Review is recorded once and
  cannot silently replace a previous review; revised extraction is a new result.
- Candidate/request edits use optimistic versions and return 409 for stale changes.
  Candidate IDs, linked visits, requests and files survive editing.
- Red `#dd0000`, navy typography, white cards and pale-gray surfaces; real native
  scrolling dialog with Save/Cancel outside its scroll area. Jinja/HTMX and small
  locally bundled JavaScript; no new Python or browser runtime dependencies.

All features are available in the isolated preview now. Windows-backed use remains
pending the schema approval and private storage arrangement below.

## Schema and migration review

Revision **`0004_candidate_desk`**, parent **`0003_jd_work_focus`**.

| New table | Purpose / main relationships |
| --- | --- |
| `work_domains` | Functional domains; stable unique key and normalized name. |
| `work_subdomains` | Parent domain FK; parent-scoped unique key/name; composite identity for pair validation. |
| `candidates` | Candidate-confirmed profile; optional domain/subdomain FKs, composite parent validation, non-unique mobile search index. |
| `candidate_visits` | Many visits per candidate; optional existing staff FK; staff-reported authority observation. |
| `job_search_requests` | Candidate-led work requests; candidate and assigned staff FKs; no JD relationship. |
| `candidate_documents` | Immutable private file metadata/version; candidate/staff FKs and same-candidate source lineage. |
| `resume_parse_results` | Append-only pasted payloads with separate one-time review; composite document FK ensures an ORIGINAL_RESUME version. |

The [schema reference](stage-3-schema.md) lists **every column, type, nullability,
default, index and constraint**. Minor additions to the proposed field list are
candidate/request `version`, request `created_at` alongside `opened_at`, normalized
catalog-name columns, composite-key support and parse `document_kind` for DB-level
original-resume enforcement. No eighth table, login table, job-role master, candidate
applications, pgvector fields or matching module was added.

[Reviewed upgrade SQL](../outputs/stage-3/0004_candidate_desk.sql): **7 CREATE TABLE,
9 CREATE INDEX, 13 RESTRICT foreign keys, 29 CHECK constraints, 9 UNIQUE constraints**,
7 primary keys and the standard Alembic ledger UPDATE. No DROP, ALTER of existing
tables, business-record UPDATE/INSERT/DELETE, extension changes or role commands.
SHA-256: `2881a16cef86ab87a12b06c40ce21b5af0820f010069a57fa716500781377253`.

Migration generation compared revision 0003 against model metadata in isolation;
it detected only these seven additions. Tests compare migrated schema with ORM
metadata, exercise upgrade/downgrade in isolation, and verify existing company/JD
rows and column definitions survive unchanged. Revisions 0001–0003 were not edited.
Downgrading 0004 drops Stage 3 tables and is destructive to any future Stage 3 data;
it is not an approved live rollback action.

### Candidate history: separate approval item

Existing `activities.job_id` and `tasks.job_id` are mandatory JD relationships. They
cannot represent candidate edits or candidate-led searches without fake JDs. They
were therefore not repurposed.

Candidate editing maintains `updated_at` and `version`, but **does not retain old
profile values**. Proposed optional eighth table, not implemented or migrated:
`candidate_events(id UUID PK, candidate_id FK RESTRICT, event_type TEXT,
changes JSONB, actor_staff_id UUID NULL FK RESTRICT, occurred_at TIMESTAMPTZ)`.
A proposed diff is `{"fields":{"email":{"before":null,"after":"..."}}}` with
self-selected/unverified attribution. If approved separately, tests should verify
one event per meaningful edit, no event on no-op, immutable event APIs, stale-write
rejection and profile/event rollback together. Do not treat visit notes as edit history.

## Main code and call paths

**Register Walk-in:** `candidate_form.html` → `desk.mjs` →
`POST /api/candidates` → `CandidateCreate` →
`CandidateService.create_candidate()` → normalize/lock mobile and check explicit
confirmation → validate active catalog/staff → insert candidate → insert first
`CandidateVisit` when source is Walk-in → optionally `JobSearchService._add()` →
flush/read response → commit once → open persistent profile. Any visit/request
failure rolls back the candidate too. `VisitService.register_walkin()` is the
service wrapper for callers explicitly registering a walk-in.

**Edit Candidate:** same dialog prefilled from `CandidateRead` → JS sends only changed
profile fields plus version and duplicate confirmation → `PATCH /api/candidates/{id}`
→ `CandidatePatch` (omitted versus explicit null retained) →
`CandidateService.update_candidate()` locks the existing row, validates version and
merged profile/catalog, checks changed mobile, updates fields/version/timestamp and
commits. No linked IDs/files/visits/requests are replaced.

**Upload Original → Download Original:** document form sends raw file bytes to
`POST /api/candidates/{id}/documents?kind=ORIGINAL_RESUME` with a percent-encoded
`X-Document-Filename` header (filename is not put in an access-log query string).
The route bounds the stream; `CandidateDocumentService.upload_document()` locks the
candidate to serialize versions. `LocalDocumentStorage.save()` validates the plain
filename, streams/hash-writes a private temporary file, checks PDF/DOCX structure,
then atomically publishes an opaque UUID key without replacing a prior file.
Metadata inserts and commit are service-controlled; transaction failure removes
that newly stored file. `upload_original_resume`, `upload_modified_resume` and
`upload_authority` are narrow wrappers of the same service operation.

`GET /candidates/{candidate_id}/documents/{document_id}/download` →
`download_document()` verifies candidate/document ownership → storage validates the
opaque key and file existence → attachment-only `FileResponse`, with `no-store`,
`nosniff` and sandbox headers. Storage paths/keys are excluded from the document API.
Missing file returns a controlled 404; metadata is retained for recovery.

**Paste Claude / ChatGPT JSON:** form chooses provider and an exact original version
→ `POST /api/candidates/{id}/resume-parses` → `ResumeParseCreate` requires a finite
JSON object within 256 KiB → `ResumeParseService.add_parse_result()` verifies document
ownership/kind and optional staff → insert preserved JSONB payload → commit.
`list_parse_results()` returns history; `review_parse_result()` locks the result and
records one employee review. No approved `ResumeExtraction` contract exists, so
status remains **Structurally checked** even after human review. `schema_version=1`
identifies the stored envelope, not an approved extraction schema. No profile
promotion or external model call occurs.

Other services: `VisitService.record_visit/list_visits_for_day` manage repeat visits
and office-local date boundaries; `JobSearchService.create_request/update_request/
list_due_requests` manages candidate-led follow-ups; `DomainCatalogService` creates,
renames and deactivates catalog entries. `repository.py` contains read/lock queries
with no commits. Shared `require_active()` validates new staff associations while
retaining inactive historical IDs. `CandidateJSONLimit` bounds JSON bodies before
FastAPI parses them; uploads have a separate byte-stream limit.

## File map

New application files in `src/jobmitra/modules/candidates/`:

- `constants.py`: approved classifications and state/UT options.
- `models.py`: seven mapped classes and explicit table registry.
- `schemas.py`: create/patch/read validation, mobile/catalog normalization, JSON limits.
- `repository.py`: queries, locks, catalog/directory/document/history reads.
- `service.py`: candidate, visit, search, catalog and parse business transactions.
- `storage.py`: `DocumentStorage` protocol and private local implementation.
- `documents.py`: versioned uploads, lineage, compensation and downloads.
- `limits.py`: bounded JSON request middleware.
- `router.py`: APIs, private downloads and server-rendered pages.

New `templates/candidates/`: `base.html`, `directory.html`, `candidate_rows.html`,
`candidate_form.html`, `new.html`, `profile.html`, `today.html`, `visits.html`,
`visit_form.html`, `visit_rows.html`, `requests.html`, `search_form.html`,
`search_rows.html`, `domains.html`, `documents.html`.
New `static/candidates/desk.css` and `desk.mjs`: v5-style forms, duplicate lookup,
dependent selects, modal controls and persistent submissions.

Shared integration changes:

- `core/config.py`, `.env.example`: explicit storage root and size limit.
- `main.py`: candidate router/static mount and bounded JSON middleware.
- `core/pages.py`: explicit template group, default remains Stage 2.
- `core/workflow.py`: shared unavailable-migration message is stage-neutral.
- `templates/stage2/base.html`: Candidate Desk navigation and overridable brand/assets.
- `migrations/env.py`: include only approved Stage 3 tables in metadata comparison.
- `migrations/versions/0004_candidate_desk_add_paperless_candidate_desk.py`: additive revision.
- `scripts/test_stage3_isolated.py`: isolated migration generation, tests and preview.
- `tests/conftest.py`: guarded shared workflow DB fixture, initialized once per run.
- `tests/test_stage2.py`: reuse fixture and recognize the new head/table set; existing
  business assertions retained. `tests/test_stage3.py`: focused new coverage.
- `README.md`, this review, `stage-3-schema.md`, and the reviewed SQL artifact.

Stage 1/2 models, business services, migration sources and stored data were not changed.
The two supplied reference files remain untracked and unmodified. No dependencies
were added and no new Markdown report outside these implementation/schema references
was generated.

## Storage configuration, backup and deployment

`JOBMITRA_DOCUMENT_STORAGE_ROOT` has **no default**. Upload/download remains disabled
with a controlled error until an absolute, existing, private non-static directory
is configured. Missing directories/mounts are not created automatically. For Mac
local development, deliberately create a private directory (mode 0700) under the
ignored `private-data/` root, then configure its absolute path in `.env`. New file
bytes are mode 0600. `JOBMITRA_DOCUMENT_MAX_BYTES` defaults to 12 MiB.

PDF signature/end marker and DOCX ZIP/XML content checks reject mismatched files,
unsafe paths, encrypted ZIP entries, macro-bearing DOCX and oversized expansion.
This is bounded format validation, not malware scanning or verification that resume
claims/signatures are genuine. Files are not served through static assets.

Production files on Windows require a separate deployment arrangement: either move
FastAPI to Windows with a private native path and appropriate ACLs, or explicitly
mount an authorized secured SMB share on the Mac and configure that absolute mount
path. A Windows `C:\\...` path is not a Mac directory. Mount availability, ACLs and
reliable atomic publication must be verified before real uploads. This task did not
mount shares or change Windows configuration.

Back up **both** PostgreSQL metadata and the entire private file root. Pause uploads
while taking a coordinated DB/file snapshot, preserve UUID storage keys, then verify
sizes/SHA-256 and test restoring both. A database dump alone cannot restore resumes.
File/SQL compensation handles ordinary errors but cannot make a process crash or
an uncertain network commit a distributed transaction; recovery should reconcile
opaque keys against metadata before removing anything. Never automatically prune
unreferenced files without review.

Use `--no-access-log` when starting the LAN app to avoid recording candidate search
queries. Existing self-selected staff attribution is not authentication; no login or
new authorization system was introduced. Keep this deployment within the existing
trusted office access boundary and arrange private file backups/access before use.

## Verification and manual acceptance

Final focused command:

```sh
.venv/bin/python scripts/test_stage3_isolated.py --pytest-args \
  tests/test_stage3.py \
  tests/test_stage2.py::test_additive_migration_roundtrip_preserves_stage1_and_models \
  tests/test_stage2.py::test_pages_fragments_local_assets_and_no_fake_candidate_metrics \
  tests/test_company_migration.py::test_migration_matches_models_and_roundtrips
```

**34 passed in 2.42 seconds**, with one existing Starlette/httpx deprecation warning.
Ruff passed for changed Python files. No unrelated full regression suite ran.
The runner removes inherited database variables, starts PostgreSQL 18 with TCP
**disabled**, checks the actual Unix socket/data directory, and sets a temporary
private storage root. Tests additionally use per-test temporary file directories;
the runner tears down the DB and storage on exit. No production files were read.

Coverage includes required fields/email, null versus omitted PATCH, stable UUIDs,
36 state/UT choices, independent salary fields, duplicate confirmation, atomic
walk-ins, repeat visits, inactive staff retention, catalog constraints/deactivation,
independent requests/overdue, PDF/DOCX byte-identical download, immutable versions,
traversal/type/size rejection, absent storage/file handling, transaction cleanup,
modified lineage, authority kind/status, exact-version parse history, JSON limits,
review separation, cross-candidate checks, page rendering, migration preservation
and Stage 1/2 compatibility. The shared fixture was corrected after a combined-run
seed collision; the final combined run passes.

Browser verification used only synthetic preview records. A walk-in was created
through the form, its original PDF uploaded through the file control, and Claude
JSON saved against original v1; reload retained the profile/file/parse result.
Editing the candidate email through the form persisted the change and preserved
the candidate UUID.
Desktop 1440×1000 and mobile 390×844: internal form scrolling with visible Save/Cancel;
mobile document width 390 px and footer bottom 831 px within the 844 px viewport.
Screenshots: [desktop form](../output/playwright/stage3-candidate-form-desktop.png),
[mobile form](../output/playwright/stage3-candidate-form-mobile.png),
[edited desktop profile](../output/playwright/stage3-candidate-profile-desktop.png).

Preview: <http://127.0.0.1:8766/candidate-desk>. The banner identifies isolated test
data. To start a fresh empty preview after it stops:

```sh
.venv/bin/python scripts/test_stage3_isolated.py --serve
```

1. Add a synthetic staff member in Staff and approved sample labels in Domain Catalog.
2. Register Walk-in with name/mobile/email; verify one profile and one visit. Add a
   Foundit profile and verify no automatic visit/request. Try the same mobile and
   explicitly resolve the duplicate warning.
3. Edit the profile, clear email or relocation, save and reload; UUID and linked
   records remain. Record a second visit against that profile.
4. Start a candidate-led request; assign staff, set a past follow-up date, and use
   the due filter. Edit status without expecting any JD selection/application.
5. Upload an original PDF/DOCX, download it, then upload v2. Upload a reviewed modified
   copy referencing an original and an authority document; earlier files remain.
6. Paste ChatGPT/Claude JSON linked to v1, review it, and verify manual skills stay
   unchanged. Check responsive form scrolling and persistent Save/Cancel controls.

## Required approvals / limitations

- Live migration is pending. Last known Windows revision was 0002; 0003 was prepared
  separately. This task did not reconnect to confirm its current status. Applying
  0004 requires 0003; **do not silently include the previously unapproved 0003**.
  Confirm prerequisites and scope when authorizing deployment, take a fresh backup,
  then review the exact migration range before any Windows write.
- Production private storage/mount and coordinated backups are not arranged by this
  implementation. There is deliberately no fallback storage folder.
- Full candidate profile edit history is deferred pending explicit approval of the
  proposed eighth table. Only profile timestamp/version is retained now.
- Approved extraction-schema validation, resume generation, candidate applications,
  matching, verified placement/selection and Stage 4 screening remain out of scope.

**May I apply the reviewed additive Stage 3 migration to Windows `jobmitra_dev`?**
No migration will be applied until separately approved, including any unmet 0003 prerequisite.

# CODEX IMPLEMENTATION REQUEST — Jobmitra Stage 3 Candidate Desk

**Objective:** Implement the approved paperless Candidate Desk in the existing Jobmitra FastAPI application. This is an **implementation task**, not another UI mockup or lengthy planning-only exercise. Preserve Stage 1 Company Management and Stage 2 JD Tracking. Implement production-oriented backend, persistent Jinja/HTMX UI, and focused tests, but **stop before executing any migration or writing data to Windows PostgreSQL**.

**Repository on Mac:** `/Users/mac/Documents/jobmitra/sop-pipeline`.

**Deployment context:** FastAPI runs on the Mac for current development; PostgreSQL runs on Windows at `192.168.1.51:5432`, database `jobmitra_dev`, application role `jobmitra_app`. Do not print credentials. The final office system is intended to be LAN-hosted, with private backed-up resume storage on the Windows server once deployment/storage access is explicitly arranged.

**UI reference:** `Jobmitra_Stage3A_Candidate_Desk_UI_v5_Email.html` (attach/provide this file to Codex if it is not in the repository). This file is a browser-memory prototype, **not** persistent application code. Follow its Jobmitra design: red `#dd0000`, navy typography, white cards, light gray background, uncluttered forms and a scrolling modal with visible Save/Cancel actions. Do not copy its demo records or client-side persistence into production. Earlier candidate UI versions/specifications are historical; v5 plus decisions below is authoritative.

## Execution plan and review gates

**Step 0 — Repository preflight, read-only.** Confirm `git status`, current branch/last checkpoint commit and `.gitignore`; do not overwrite uncommitted work. Inspect existing FastAPI structure, SQLAlchemy base/models, Pydantic, Alembic revision tree, Stage 1/2 tables and conventions, existing staff and task/history capabilities, local storage modules, and any pre-existing ATS parsing contracts. Print a short repo-specific implementation map. If there is uncommitted user code or major schema conflicts, stop and report those exact blockers rather than overwriting. No new repetitive LAN/network diagnostics; `psql` access was already established from Mac Terminal.

**Step 1 — Data model + additive migration.** Implement the minimal tables specified below using existing project conventions, while preserving established Staff/Company/Job tables and migration history. Generate and inspect migration SQL. Any migration validation must run only against an explicitly isolated disposable test DB/schema. Do **not** run `alembic upgrade head` against the Windows database or seed live demo records.

**Step 2 — Backend.** Implement SQLAlchemy models, Pydantic request/response schemas, repositories, services, and FastAPI routes for candidates, domain catalog, office visits and job-search requests. Add file upload/download and resume JSON handling using a private file storage abstraction. Keep business logic in services, queries in repositories, and transactions service-controlled.

**Step 3 — UI.** Integrate real server-backed pages into existing navigation: Today Dashboard, Candidates, Candidate Profile, Office Visits, Job Search Requests, Domain Catalog, Resumes & Parsed JSON. Reuse existing UI patterns (Jinja2, HTMX, minimal JS) and existing `staff_members`. Responsive desktop/mobile, scrollable Add Candidate dialog, footer buttons accessible. No second standalone app and no fake counters.

**Step 4 — Focused tests + review.** Test isolated database and private temporary file storage; show short test results, changed files, ORM/route/service mapping, migration SQL summary and any deferred decisions. **Do not commit/push, modify real Windows data, or start Stage 4 ATS without approval.** Stop before live migration and ask for explicit approval to apply the additive migration.

## Proposed data model / table boundaries (review before live migration)

Reuse existing `staff_members`, `companies`, `company_contacts`, `job_requirements`, `tasks` / `activities` *where structurally and semantically appropriate*. Do not recreate these.

Proposed Stage 3 tables, **7 new core tables** (verify no same-purpose tables already exist before creating and report deviations for review):

1. **`work_domains`**: `id UUID PK`, stable `key`, unique normalized `name`, `is_active`, timestamps. Domain represents **functional work domain**, NOT company industry. Allow Add/Rename/Deactivate from Domain Catalog. No auto-deletion of referenced entries.
2. **`work_subdomains`**: `id UUID PK`, `domain_id UUID FK work_domains`, stable parent-scoped normalized `key`/name, `is_active`, timestamps, unique `(domain_id, normalized_name)`. Only show subdomains belonging to selected domain; reject incorrect domain–subdomain pairs, ideally enforced at DB as well as service boundary.
3. **`candidates`**: `id UUID PK`; `full_name` required/nonblank; `mobile` and normalized search value (preserve original text and leading zero); `email` nullable; `source` (`Walk-in`, `Foundit`, `WhatsApp`, `Referral`, `Existing database`, `Other`); `role_title` free text (suggest previous roles, **no job-role master table**); `domain_id`, `subdomain_id` optional FKs; `qualification`; `experience_months` nullable nonnegative; `skills TEXT[]`; `current_location`; `preferred_locations TEXT[]`; `hometown`, `home_state`; `ready_to_relocate BOOLEAN NULL` (Yes / No / Not specified, never inferred); `current_salary_amount NUMERIC`, `current_salary_period`, `current_salary_basis`; `expected_salary_amount NUMERIC`, `expected_salary_period`, `expected_salary_basis`; optional `last_salary_raw`; `notice_period_text`; `created_at`, `updated_at`. Salary periods are `Monthly`, `Annual`, `Unknown`; bases `CTC`, `Gross`, `Take-home`, `Unknown`. Null amounts stay null; do not guess units or silently convert salary figures. Preserve sensible original candidate-stated wording where necessary. If current architecture offers better normalized contact fields, reuse without destructive change.
4. **`candidate_visits`**: `id UUID PK`, `candidate_id FK`, `visited_at TIMESTAMPTZ`, `purpose`, nullable `recorded_by_staff_id FK`, authority-status observation (`Not recorded`, `Pending`, `Signed (reported)`, `Not signed`), optional `note`, `created_at`. **A visit is not a new candidate.** Multiple visits belong to one candidate. Signed status is staff-reported; not evidence that an actual signed document was stored.
5. **`job_search_requests`**: `id UUID PK`, `candidate_id FK`, `desired_role`, preferred locations (array or clear text per repo conventions), `assigned_staff_id FK`, `status` (`Searching`, `Interviewing`, `On Hold`, `Placed`, `Closed`), `next_action`, optional `follow_up_date`, `note`, opened/closed/updated timestamps. This is a **candidate-led job-finding task**, independent of company JDs. Do not auto-create it for every Foundit candidate or equate `Placed` text with a verified company selection. No automatic job matching or fake JD/application links in this stage.
6. **`candidate_documents`**: `id UUID PK`, `candidate_id FK`, `kind` (`ORIGINAL_RESUME`, `MODIFIED_RESUME`, `AUTHORITY`), immutable uploaded file metadata (`original_filename`, `storage_key`, `content_type`, `size_bytes`, `sha256`, `created_at`, optional uploaded_by_staff_id), per-candidate/per-kind version, optional `source_document_id` for modified-resume lineage, optional `approval_status`, and explicit current-original-resume marker or stable latest-resolution rule. Keep original versions immutable, never overwrite earlier file bytes. A modified resume is an explicitly reviewed/uploaded derived copy; **do not fabricate experience, qualifications, skills or contact details**. Display consultancy contact as such if candidate authorized; never silently replace candidate identity/contact. Store signed authority documents with their own kind and status.
7. **`resume_parse_results`**: `id UUID PK`, `document_id FK candidate_documents` referring to one **specific original resume version**, provider `ChatGPT` / `Claude`, nullable model label, schema version, `parsed_json JSONB` (preserve payload), JSON/Pydantic validation and review status distinguished, optional pasted/reviewed staff IDs, timestamps. Multiple results can link to one resume. New resume version does not rewrite existing parse results. The UI accepts **manual paste only**; no external model invocation in this phase. Do not mark a JSON result as schema-validated if it merely parses syntactically.

**Change history:** Candidate profile edits should be reviewable. First inspect existing `activities` capability. Reuse it only if it can express candidate events accurately without distorting mandatory JD relationships. Otherwise **propose**, rather than silently create, an optional `candidate_events` table (which would be an 8th table), with its purpose/diff shape and tests; do not store faux candidate events in `candidate_visits`. At minimum `updated_at` must be maintained. Any approval-dependent extra migration is a separate review item.

**Foreign key safety:** Dynamic staff may become inactive; existing names/IDs and historical visits/assignments remain intact. Keep candidates and resumes non-cascading/retained, use UUID associations, prevent malformed references and conflicting duplicate active catalog labels. Do not alter existing company/JD records or pgvector settings.

## User-facing workflows (all persistent once migrated)

**A. Quick Add Candidate / Register Walk-in**
- Main form must show Name, Mobile, **Email (optional)**, Source, Current/Last Job Role (free text + suggestions), **Domain**, **Sub-domain**, Qualification, Experience, Skills, Current Location, Preferred Work Locations, **Ready to Relocate** (Yes/No/Not specified), **Hometown**, **Home State/UT** (28 states and 8 Union Territories), Current Salary amount + Monthly/Annual selector, Expected Salary amount + Monthly/Annual selector, optional Last Salary wording, Notice/Availability.
- Do not hide Qualification/Skills/Preferred Locations in an unnecessary More Options section. Salary basis may be optional and minimally presented; preserve Unknown rather than guessing.
- Mobile is mandatory for manual *quick registration* per current approved UI; database may allow unknown contacts only if required for controlled imports and clearly differentiated. Normalize for search but do not silently change stored original. Email optional, editable, searchable, validate format.
- Live duplicate check by mobile: show possible existing profiles; **no auto-merge and no blanket global unique mobile constraint**. Only proceed with a second person when explicitly confirmed. A new Walk-in creates one candidate and **one initial office visit**, in one logical unit of work. New Foundit candidate does not automatically get a visit or personal job-search request; the optional checkbox for job search is explicit.
- Add, edit and search should retain stable candidate IDs and all linked visits/files/requests. NULL vs omitted PATCH fields must be distinguished. A repeat visit uses the existing candidate profile.

**B. Office Visits / Paperless Register**
- Search existing candidate by name/mobile first; record visit date/time, purpose, staff selector, optional notes and authority status observation. Allow multiple visits; list Today / recent visits with actual data only.
- Show visits in candidate profile. No paper-style separate candidate duplicate per visit.

**C. Candidate Job Search Requests**
- Independently create/update requests for walk-ins/returning jobseekers. Role, locations, employee, status, next action, follow-up date. Team worklist for pending/overdue callbacks; overdue is computed, not a separate stored status. Keep company-led sourcing and candidate-led requests separate but point to the **same candidate profile**.
- Optional read-only view of relevant *actual* Stage 2 JDs if effortless; do not create fake match scores or Stage 4 candidate applications.

**D. Domain Catalog**
- Managed Domain + dependent Sub-domain selectors; Add New, Rename and Deactivate with normalized duplicate warnings. Job Role remains editable free text with suggestions, no additional `job_roles` table. Domain is not company industry. Existing ATS draft of 16 work domains / 27 industries remains **unapproved**; do not seed invented/demo catalog labels into Windows. If reference taxonomy file exists, inspect it, report current approval status, and import only with explicit approval.

**E. Resume and documents — priority functionality**
- Candidate Profile → Resumes & Parsed JSON: **Upload Original Resume**, **Download Original**, **Upload New Version**, **Upload/Download Modified (Jobmitra) Resume**, **Upload/Download Authority**, **Paste ChatGPT JSON**, **Paste Claude JSON**, **View parse history**.
- Support PDF and DOCX file types, enforce configurable size limit, verify actual content type as feasible, reject unsafe filenames/path traversal. Use generated UUID storage keys and a private, non-static storage root. Never expose full filesystem paths or raw candidate records in logs. Storage key is relative/opaque; database stores metadata only. File missing => controlled error, not database corruption.
- Reuse one `DocumentStorage` interface with local filesystem implementation. **Development:** explicit Mac private storage root configured by environment, excluded from Git, backed up for tests/real usage; no claim Mac Python can read a Windows `C:\...` path. **Office production target:** private Windows server storage when FastAPI is moved there, or a separately approved secured mounted SMB share while Mac still hosts FastAPI. Do not hardcode production path or quietly save to an unintended fallback folder. Include a migration/backup note for BOTH DB and stored files.
- Use temporary file + atomic move where available, and service-controlled DB transaction plus compensating cleanup for failures; no orphan metadata claiming files exist. Hash streaming uploads with SHA-256. No actual modified resume *generation* in Stage 3; allow uploading and downloading an authorized, accurately edited version. Preserve original/source lineage.
- Parsing: staff manually pastes JSON already obtained from ChatGPT/Claude; validate that it is a JSON object, enforce payload size, retain source resume ID, provider and model if known. If the repository contains an approved Pydantic ResumeExtraction contract, reuse it when compatible; otherwise save as **Unreviewed / Structurally checked** and clearly mark more comprehensive validation pending. Never silently promote extracted fields over staff/candidate-confirmed profile fields. Never send resumes, PII, or parsed content to external AI automatically.

## Python architecture & routes

Use existing package/module conventions rather than inventing another framework. Suggested responsibilities:

- `Candidate`, `CandidateVisit`, `JobSearchRequest`, `WorkDomain`, `WorkSubdomain`, `CandidateDocument`, `ResumeParseResult` — SQLAlchemy models.
- Pydantic classes for `CandidateCreate/Patch/Read`, `VisitCreate/Read`, `JobSearchRequestCreate/Patch/Read`, domain/subdomain create/patch/read, `DocumentRead`, `ResumeParseCreate/Read`.
- `CandidateService`: `create_candidate`, `update_candidate`, `find_possible_duplicates`, `search_candidates`, `get_candidate_detail`.
- `VisitService`: `register_walkin`, `record_visit`, `list_visits_for_day`.
- `JobSearchService`: `create_request`, `update_request`, `list_due_requests`, `list_candidate_requests`.
- `DomainCatalogService`: `add_domain`, `add_subdomain`, `deactivate_category`, `list_active_catalog`.
- `CandidateDocumentService`: `upload_original_resume`, `upload_modified_resume`, `upload_authority`, `download_document`, `list_document_versions`, `set_current_resume`.
- `ResumeParseService`: `add_parse_result`, `list_parse_results`, `review_parse_result`.
- Small repository classes for SQL queries with no hidden commits; service owns transaction boundary. Reuse `staff_members` and current HTTP conventions.

Provide minimal REST/HTMX endpoints following project patterns (names can adapt): `/candidates`, `/candidates/new`, `/candidates/{id}`, `/candidates/{id}/visits`, `/candidates/{id}/job-search`, `/candidates/{id}/documents`, `/candidates/{id}/documents/{document_id}/download`, `/candidates/{id}/resume-parses`, `/office-visits`, `/job-search-requests`, `/domains` and `/subdomains`. Protect file handling endpoints from traversal; never construct a download path from user-submitted filename. No extra microservices, message broker or vector indexing.

## Tests and verification

Run narrowly scoped tests against an **isolated disposable database** and temporary filesystem. Existing Windows DB and real candidate files must remain read-only/unmodified in this implementation run.

Minimum tests:
- Quick registration required fields, optional email, email format, candidate edit stability, and absent vs explicit null.
- Domain/subdomain parent mismatch rejected; duplicate catalog names casefolded; deactivation retains relationships; free-text role accepted.
- 28 states + 8 UT choices; hometown independent; relocation true/false/unknown preserved.
- Current and expected salary units independent, amounts Decimal/NUMERIC, unknown basis/period preserved, no silent annual/monthly conversion.
- Mobile duplicate warning without automatic merge; repeat visits produce distinct visit records for same candidate.
- Walk-in creates candidate + first visit atomically; Foundit-only entry does not invent visit/job-search request.
- Candidate-led job search request persists separately from company JD and supports follow-ups without fake placements.
- Upload original PDF/DOCX, retrieve identical bytes, version immutability, metadata/sha integrity, private storage path safety, missing file handling, rollback/cleanup on simulated failure.
- Modified resume has source linkage and can be downloaded; never overwrites original; authority document separately typed.
- Parsed JSON linked to exact resume version; multiple providers; reject bad JSON and non-object payloads; AI results never overwrite manual profile.
- Staff selected by ID (not hardcoded); inactive staff history survives. Focused UI route rendering and scrolling modal on desktop/mobile where Playwright exists.
- Migration adds only intended tables/indexes/FKs/checks; no unexpected alterations/drops; Stage 1/2 tests unaffected by model registration.

**If full dependency test environment is unavailable**, do not fabricate results; run what is available and list omitted tests with reason. Avoid generating huge screenshots/reports outside the minimal review folder.

## Final report / mandatory stop

Return a concise, reviewable result:

1. Actual git branch / base commit and changed file list.
2. What candidate registration, visits, requests, resumes and parsing UI actually do now; which remain pending due to unapplied migration.
3. Exact new tables, columns, FKs, indexes, constraints and the generated Alembic revision/down_revision. Explicitly explain any proposed 8th table for history.
4. Function-by-function call path for: **Register Walk-in**; **Edit Candidate**; **Upload Original Resume → Download Original**; **Paste Claude/ChatGPT JSON**.
5. Filename/file storage root configuration, backup requirements, and migration-to-Windows storage plan.
6. Tests actually run and outcomes, with isolated DB/file-storage proof.
7. Migration SQL diff review with proof no `DROP`/destructive Company/JD/pgvector change.
8. Unresolved blockers and concrete manual acceptance instructions.
9. Ask **“May I apply the reviewed additive Stage 3 migration to Windows `jobmitra_dev`?”** and stop until explicit approval.

**Absolute prohibitions without approval:** No Windows PostgreSQL migrations/DDL/seed/role changes, no wiping/importing candidate files, no new external model calls, no unauthorized real candidate data tests, no git commit/push/reset/clean, no modifying Stage 1/2 business records. Do not give me another generic architecture essay—implement maintainable code and show me what changed.

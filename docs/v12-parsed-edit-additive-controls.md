# Added candidate controls and API mapping

The immutable approved reference has 334 original control occurrences. See [the original control matrix](v12-parsed-edit-control-matrix.md). These additions are scoped to the existing Candidate Desk styling and workflows. Counts below describe field definitions; repeatable rows and version buttons depend on actual database records.

## Complete Edit Candidate Details

All values are loaded from `GET /api/v12/approved/candidates/{candidate_id}/profile`. Only edited values are sent to `PATCH` at that URL, with the displayed revision, declared actor, UUID idempotency key, explicit approved field names and normalized-notice confirmation. Save reads the profile back and refreshes canonical state/search. Cancel performs no request. Escape, focus containment, scrollable form body and accessible section disclosures are included.

| Group | Controls / canonical fields |
|---|---|
| Personal/contact (6) | `core_full_name`, `core_phone`, `core_email`, `core_links`, `core_current_city`, `core_preferred_cities` |
| Professional (9) | `core_job_title`, `core_current_employer`, `core_experience_years`, `core_qualification`, `core_primary_domain`, `core_skills`, `core_professional_summary`, `core_availability`, `core_source` |
| Salary/notice (7) | `core_current_salary_inr`, `core_current_salary_period`, `core_current_salary_basis`, `core_expected_salary_inr`, `core_expected_salary_period`, `core_expected_salary_basis`, `core_notice_days` |
| Additional profile evidence (6) | `extra_hometown`, `extra_home_state`, `extra_subdomain`, `extra_ready_to_relocate`, `extra_experience_months`, `extra_notice_period_text` |
| Explicit normalization | `noticeVerified` confirms verified notice days; original notice evidence/history remain separate |
| Employment history (7 field types) | Employer, job title, start date, end date, role experience months, responsibilities, achievements; Add / Remove entry |
| Education history (4) | Institution, qualification, start year, end year; Add / Remove entry |
| Certifications (3) | Name, issuer, issue date; Add / Remove entry |
| Projects (3) | Name, role, description; Add / Remove entry |
| Actions | Save reviewed changes, Cancel; validation/conflict status shown in the form |

The four collections use typed structures in the pre-existing optional `candidate_profile_versions` extension. Original PostgreSQL UUID, SQLite ID, candidate code and source JSON are not editable controls. Monetary inputs are submitted as decimal strings. Unknown salary period is displayed honestly; fractions are preserved.

## Parsed Resume

Base path below is `/api/v12/approved/candidates/{candidate_id}`.

| Controls | Service / actual behavior |
|---|---|
| `parsedJsonSource` | Selects an exact owned ORIGINAL or JOBMITRA_STANDARD version from canonical resume metadata |
| `profileParsedFile`, `profileParsedText`, `profilePreviewParsed` | `POST {base}/parsed-drafts`; preserves uploaded UTF-8 JSON bytes or pasted text, validates allowed proposals, leaves master fields unchanged |
| `parsedUnlock` | Existing `/api/v12/access` capability session and declared reviewer name; private history is server protected |
| `parsedPdfSource`, `parsedPdfExtract` | `POST {base}/resumes/{resume_id}/extract`; local text/explicit-label extraction into an unapproved draft |
| `parsedPdfPreview` | Authenticated `GET {base}/resumes/{resume_id}/preview`; exact PDF bytes in native inline viewer |
| `parsedPdfDownload` | Authenticated `GET /api/ats-v2/candidates/{candidate_id}/resumes/{resume_id}/download`; client verifies stored SHA-256 before download |
| `parsedPdfFile`, `parsedPdfPreparation`, `parsedPdfOriginal`, `parsedPdfNotes` | `POST /api/ats-v2/candidates/{candidate_id}/resumes` with JOBMITRA_STANDARD, metadata and reuse header; reads back existing/new version, then extracts it |
| `data-parsed-open` | `GET {base}/parsed-drafts/{draft_id}`; evidence, warnings, source hash, status and current profile revision |
| `data-parsed-download`, Download preserved JSON | `GET {base}/parsed-drafts/{draft_id}/download`; source bytes checked against the artifact hash |
| `data-parsed-review-field` | One unchecked checkbox per validated proposal; current, proposed and source evidence displayed |
| `confirmParsedIdentity` | Explicit source/candidate identity confirmation when the document name differs |
| `confirmParsedApply` | `POST {base}/parsed-drafts/{draft_id}/approve`; selected fields only, revision conflict check, one transaction, immutable reviewed version, API read-back |
| `discardParsedPreview` | Keeps the persisted draft; clears selections without changing candidate fields |
| Evidence disclosures | Extracted PDF text and preserved original JSON; no master update |
| Version history | Each row shows actual version ID, source version, timestamp and review/extraction status |

## Resumes tab reuse

Original and Jobmitra Altered histories remain separate. `data-resume-download` downloads existing bytes with checksum verification. `data-resume-current` uses the existing current-version service with the expected current ID; prior files remain. Parsed Resume selection creates no PDF copy. Identical uploaded bytes and provenance reuse the same version; different provenance can create a metadata version sharing the verified immutable file. Existing ORIGINAL upload remains available.

## State and audit

`GET /api/v12/approved/state` refreshes canonical UI projections. `GET /api/v12/approved/search` queries approved professional evidence. `GET {base}/profile-history` provides immutable before/after records. No browser storage is a source of truth. No new controls were added to Companies, JD Tracking, Proposal or Email Studio in this pass.

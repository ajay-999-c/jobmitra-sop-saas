# Stage 2 schema for review

Status: implemented, tested in disposable PostgreSQL 18, and **approved and applied
to Windows on 2026-10-20**. See the [deployment record](stage-2-windows-deployment.md).

Applied revision: `0002_jd_tracking`; parent: `0001_company_management`.

Pending addition: `0003_jd_work_focus` adds only `current_work_focus TEXT NULL` to
`job_requirements`, with `ck_job_work_focus` allowing the seven approved codes.
There is no default/backfill or new table. This field is **not yet on Windows**;
see the [tracker review](stage-2-process-tracker-review.md) for exact values and SQL.
The table definitions below describe the applied revision 0002.

Exactly five new business tables; the two existing Company tables remain unchanged.
Every foreign key below uses `ON DELETE RESTRICT`. There are no cascade deletions,
extension changes, candidate tables, taxonomy tables or new roles.

UUID primary keys use Python `uuid4()` on insertion; no database UUID extension is needed.
`created_at`, `updated_at`, assignment and event timestamps default to database `now()`.
`updated_at` is maintained by SQLAlchemy updates, not a database trigger.
Absent employer facts remain SQL NULL; empty skill arrays and explicit Unknown salary
units are the approved defaults. Target state and task overdue labels are computed.

## Relationships

- An existing company has zero or more JDs. A JD has one company and optionally one
  existing company contact. The service verifies that the contact belongs to that company.
- Staff create JDs, act in history, confirm SHORTLIST, close JDs and own follow-up tasks.
- JD ↔ staff is many-to-many through `job_recruiters`; memberships have no rank or owner.
- Every activity and task belongs to one JD. Historical staff references remain intact.

A column marked NOT NULL is mandatory at database level. A dash in the default column
means no server default. Foreign keys do not add columns to either existing Company table.

## `staff_members` — `StaffMember`

| Column | PostgreSQL type | Nullable | Server default | Reference |
| --- | --- | --- | --- | --- |
| `id` **PK** | `UUID` | NOT NULL | `—` | — |
| `display_name` | `TEXT` | NOT NULL | `—` | — |
| `is_active` | `BOOLEAN` | NOT NULL | `true` | — |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | `now()` | — |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | `now()` | — |

Checks:

- `ck_staff_name_nonblank`: `length(btrim(display_name)) > 0`

Indexes (in addition to the primary key):

- `ix_staff_active_name` (`is_active`, `display_name`).

## `job_requirements` — `JobRequirement`

| Column | PostgreSQL type | Nullable | Server default | Reference |
| --- | --- | --- | --- | --- |
| `id` **PK** | `UUID` | NOT NULL | `—` | — |
| `company_id` | `UUID` | NOT NULL | `—` | `companies.id` (RESTRICT) |
| `company_contact_id` | `UUID` | NULL | `—` | `company_contacts.id` (RESTRICT) |
| `created_by_staff_id` | `UUID` | NOT NULL | `—` | `staff_members.id` (RESTRICT) |
| `job_title` | `TEXT` | NOT NULL | `—` | — |
| `raw_requirement` | `TEXT` | NULL | `—` | — |
| `received_at` | `TIMESTAMP WITH TIME ZONE` | NULL | `—` | — |
| `domain_key` | `TEXT` | NULL | `—` | — |
| `subdomain_key` | `TEXT` | NULL | `—` | — |
| `location_text` | `TEXT` | NULL | `—` | — |
| `work_mode` | `TEXT` | NULL | `—` | — |
| `experience_min_months` | `INTEGER` | NULL | `—` | — |
| `experience_max_months` | `INTEGER` | NULL | `—` | — |
| `salary_min` | `NUMERIC(12, 2)` | NULL | `—` | — |
| `salary_max` | `NUMERIC(12, 2)` | NULL | `—` | — |
| `salary_period` | `TEXT` | NOT NULL | `Unknown` | — |
| `salary_basis` | `TEXT` | NOT NULL | `Unknown` | — |
| `salary_currency` | `TEXT` | NULL | `—` | — |
| `vacancies` | `INTEGER` | NULL | `—` | — |
| `qualification` | `TEXT` | NULL | `—` | — |
| `required_skills` | `TEXT[]` | NOT NULL | `'{}'::text[]` | — |
| `preferred_skills` | `TEXT[]` | NOT NULL | `'{}'::text[]` | — |
| `specific_skill` | `TEXT` | NULL | `—` | — |
| `specific_skill_min_months` | `INTEGER` | NULL | `—` | — |
| `status` | `TEXT` | NOT NULL | `Draft` | — |
| `target_date` | `DATE` | NULL | `—` | — |
| `target_milestone` | `TEXT` | NULL | `—` | — |
| `target_completed_at` | `TIMESTAMP WITH TIME ZONE` | NULL | `—` | — |
| `target_completed_by_staff_id` | `UUID` | NULL | `—` | `staff_members.id` (RESTRICT) |
| `ats_json` | `JSONB` | NULL | `—` | — |
| `ats_schema_version` | `SMALLINT` | NULL | `—` | — |
| `ats_status` | `TEXT` | NOT NULL | `Not Added` | — |
| `closed_at` | `TIMESTAMP WITH TIME ZONE` | NULL | `—` | — |
| `closed_by_staff_id` | `UUID` | NULL | `—` | `staff_members.id` (RESTRICT) |
| `closure_reason` | `TEXT` | NULL | `—` | — |
| `version` | `INTEGER` | NOT NULL | `1` | — |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | `now()` | — |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | `now()` | — |

Checks:

- `ck_job_ats_state`: `(ats_json IS NULL AND ats_schema_version IS NULL AND ats_status='Not Added') OR (ats_json IS NOT NULL AND ats_schema_version IS NOT NULL AND ats_schema_version=1 AND ats_status IN ('Draft','Reviewed','Stale'))`
- `ck_job_closure`: `(status='Closed' AND closed_at IS NOT NULL AND closed_by_staff_id IS NOT NULL AND closure_reason IS NOT NULL AND length(btrim(closure_reason))>0) OR (status<>'Closed' AND closed_at IS NULL AND closed_by_staff_id IS NULL AND closure_reason IS NULL)`
- `ck_job_experience_nonnegative`: `experience_min_months >= 0 AND experience_max_months >= 0`
- `ck_job_experience_order`: `experience_min_months <= experience_max_months`
- `ck_job_salary_basis`: `salary_basis IN ('CTC','Gross','Take-home','Unknown')`
- `ck_job_salary_nonnegative`: `salary_min >= 0 AND salary_max >= 0 AND salary_min <> 'NaN'::numeric AND salary_max <> 'NaN'::numeric`
- `ck_job_salary_order`: `salary_min <= salary_max`
- `ck_job_salary_period`: `salary_period IN ('Monthly','Annual','Unknown')`
- `ck_job_shortlist_confirmation`: `(target_completed_at IS NULL AND target_completed_by_staff_id IS NULL) OR (target_completed_at IS NOT NULL AND target_completed_by_staff_id IS NOT NULL AND target_milestone IS NOT NULL AND target_milestone='SHORTLIST')`
- `ck_job_skills_no_nulls`: `array_position(required_skills,NULL) IS NULL AND array_position(preferred_skills,NULL) IS NULL`
- `ck_job_specific_months`: `specific_skill_min_months >= 0`
- `ck_job_status`: `status IN ('Draft','Active','On Hold','Closed')`
- `ck_job_target_milestone`: `target_milestone IN ('SHORTLIST','SELECTION','JOINING')`
- `ck_job_target_pair`: `(target_date IS NULL) = (target_milestone IS NULL)`
- `ck_job_title_nonblank`: `length(btrim(job_title)) > 0`
- `ck_job_vacancies_positive`: `vacancies > 0`
- `ck_job_version`: `version > 0`

Indexes (in addition to the primary key):

- `ix_job_company_status` (`company_id`, `status`).
- `ix_job_status` (`status`).
- `ix_job_target` (`target_date`); WHERE `target_date IS NOT NULL`.

## `job_recruiters` — `JobRecruiter`

| Column | PostgreSQL type | Nullable | Server default | Reference |
| --- | --- | --- | --- | --- |
| `job_id` **PK** | `UUID` | NOT NULL | `—` | `job_requirements.id` (RESTRICT) |
| `staff_id` **PK** | `UUID` | NOT NULL | `—` | `staff_members.id` (RESTRICT) |
| `assigned_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | `now()` | — |
| `removed_at` | `TIMESTAMP WITH TIME ZONE` | NULL | `—` | — |

Checks:

- `ck_recruiter_dates`: `removed_at IS NULL OR removed_at >= assigned_at`

Indexes (in addition to the primary key):

- `ix_recruiter_active_staff` (`staff_id`, `job_id`); WHERE `removed_at IS NULL`.

## `activities` — `Activity`

| Column | PostgreSQL type | Nullable | Server default | Reference |
| --- | --- | --- | --- | --- |
| `id` **PK** | `UUID` | NOT NULL | `—` | — |
| `job_id` | `UUID` | NOT NULL | `—` | `job_requirements.id` (RESTRICT) |
| `event_type` | `TEXT` | NOT NULL | `—` | — |
| `note` | `TEXT` | NULL | `—` | — |
| `changes` | `JSONB` | NULL | `—` | — |
| `actor_staff_id` | `UUID` | NULL | `—` | `staff_members.id` (RESTRICT) |
| `occurred_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | `now()` | — |

Checks:

- `ck_activity_type`: `length(btrim(event_type))>0`

Indexes (in addition to the primary key):

- `ix_activity_job_timeline` (`job_id`, `occurred_at`, `id`).

## `tasks` — `Task`

| Column | PostgreSQL type | Nullable | Server default | Reference |
| --- | --- | --- | --- | --- |
| `id` **PK** | `UUID` | NOT NULL | `—` | — |
| `job_id` | `UUID` | NOT NULL | `—` | `job_requirements.id` (RESTRICT) |
| `title` | `TEXT` | NOT NULL | `—` | — |
| `note` | `TEXT` | NULL | `—` | — |
| `assigned_staff_id` | `UUID` | NOT NULL | `—` | `staff_members.id` (RESTRICT) |
| `created_by_staff_id` | `UUID` | NOT NULL | `—` | `staff_members.id` (RESTRICT) |
| `due_date` | `DATE` | NULL | `—` | — |
| `status` | `TEXT` | NOT NULL | `Pending` | — |
| `completed_at` | `TIMESTAMP WITH TIME ZONE` | NULL | `—` | — |
| `completed_by_staff_id` | `UUID` | NULL | `—` | `staff_members.id` (RESTRICT) |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | `now()` | — |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL | `now()` | — |

Checks:

- `ck_task_completion`: `(status='Done' AND completed_at IS NOT NULL AND completed_by_staff_id IS NOT NULL) OR (status<>'Done' AND completed_at IS NULL AND completed_by_staff_id IS NULL)`
- `ck_task_status`: `status IN ('Pending','Done','Cancelled')`
- `ck_task_title`: `length(btrim(title))>0`

Indexes (in addition to the primary key):

- `ix_task_assignee_due` (`assigned_staff_id`, `status`, `due_date`).
- `ix_task_job` (`job_id`).

## Service invariants and deliberate limits

- Staff names are not unique identities. Duplicate names warn without merging UUIDs.
  Deactivation retains historical references; only active staff can record new work
  or receive new assignments. Global staff edits have no separate audit table.
- `job_requirements.version` is an optimistic concurrency token. The service locks the JD,
  compares the supplied version and increments it once with the activity for each action.
  Notes and tasks participate in the same parent-JD version protocol.
- Target date and milestone are entered/cleared together. The two nullable completion
  fields are exclusively for explicit, self-selected staff confirmation of SHORTLIST.
  Changing the target clears confirmation. SELECTION and JOINING remain tracking-only
  pending authoritative application/placement evidence in a later stage.
- Recruiter removal sets `removed_at`. Re-addition reuses the composite key, resets
  `assigned_at`, and retains previous membership events in history.
- Required/preferred skills are casefold-deduplicated at the input boundary.
  ATS schema-v1 JSON is validated separately and never populates manual criteria.
  A meaningful manual-criteria edit preserves existing JSON and marks it Stale.
- Closure requires a reason and actor/timestamp; reopening clears current closure
  fields while preserving the historical before/after event.
- Tasks are Pending, Done or Cancelled. Overdue is a local-office calendar label.
  Done requires completion attribution; Cancelled has no completion timestamp.
- Activities are append-only through application APIs, not tamper-proof database auditing.
  Actor name snapshots retain the name recorded at the time.
- Contact-company consistency, active-staff checks, ATS structure, skill cleanup and
  version increments are service rules in addition to database constraints. Direct SQL
  clients must not bypass those rules.

See [review and validation](stage-2-review.md) and [exact upgrade SQL](../outputs/stage-2/0002_jd_tracking.sql).

# Stage 2 Windows deployment — 2026-10-20

The user explicitly approved creating the tables. Revision `0002_jd_tracking`
was applied and committed on Windows PostgreSQL 18.6 at `192.168.1.51:5432`,
database `jobmitra_dev`, using the configured `jobmitra_app` account.

## Database result

The migration added exactly these five empty tables:

| Table | Purpose | Initial rows |
| --- | --- | ---: |
| `staff_members` | Dynamic employee directory | 0 |
| `job_requirements` | Company-confirmed JDs and separate ATS enrichment | 0 |
| `job_recruiters` | Multiple staff assignments per JD | 0 |
| `activities` | JD history and notes | 0 |
| `tasks` | Employee follow-up tasks | 0 |

The 131 existing companies and 108 contacts were preserved. Entire-row
fingerprints and column definitions matched before and after migration. The public
table set changed only by adding the five approved tables, and Alembic advanced
from `0001_company_management` to `0002_jd_tracking`.

Extension metadata was unchanged: `plpgsql` 1.0 is enabled; pgvector remains
unenabled in this database. No imports, seeds, role changes, extension changes or
existing business-record edits were performed.

The freshly generated offline SQL matched the reviewed
[migration SQL](../outputs/stage-2/0002_jd_tracking.sql): five CREATE TABLE statements,
eight indexes, 13 RESTRICT foreign keys, 23 CHECK constraints, five primary keys
and the Alembic revision update. It contains no company-table alterations.

## Backup and verification

A custom-format backup was created before migration from a consistent snapshot,
with row fingerprints captured from the same snapshot. Its archive catalog and
full SQL decoding were verified. Files have owner-only permissions.

- [Backup archive](../backups/stage2-20261020T100738816626Z/jobmitra_dev-before-stage2.dump)
  — 18,697 bytes.
- SHA-256: `ed6c1030e2c6ba6c7a436fa14fc0c8d28f94713165ffca8296e7772c73eed147`.
- [Backup manifest](../backups/stage2-20261020T100738816626Z/manifest.json).
- [Read-only baseline](../outputs/stage-2/windows-before-approved-migration.json).
- [Committed migration result](../backups/stage2-20261020T100738816626Z/applied-result.json).

An initial attempt rolled back because the verification code compared SQLAlchemy
type-object identities instead of SQL column definitions. The comparison was
corrected to use scalar `information_schema.columns` values. Fresh baseline checks
confirmed the rollback preserved revision 0001 and all data before retrying. The
second attempt passed the checks and committed revision 0002.

The apply transaction used bounded lock/statement timeouts and held company-table
locks while checking preservation. Existing-company fingerprints, column metadata,
table scope and extension metadata were checked before commit.

## Live UI and validation

The Mac backend was started on <http://127.0.0.1:8000> using the Windows settings.
All eight read-only requests returned HTTP 200: readiness, company API, Company
Directory, overview, requirements, new requirement, staff and tasks. Both the API
and rendered directory contained 131 companies; the headed browser visibly showed
“131 companies.” See the [HTTP results](../outputs/stage-2/windows-ui-live-20261020.json).

No full regression suite or production write tests were run during deployment.
The earlier isolated Stage 2 validation passed 61 tests; those historical results
are documented in the [review](stage-2-review.md).

Use the application:

1. Open the [Company Directory](http://127.0.0.1:8000/companies) to view existing companies.
2. Add real employees in [Staff](http://127.0.0.1:8000/staff).
3. Open [Create JD](http://127.0.0.1:8000/requirements/new), select a company and
   enter its confirmed requirement details.
4. Open the saved JD to assign recruiters, edit required skills, set a target
   and add follow-up tasks. Changes appear in its history.

If the backend has been stopped, restart it from the project root:

```sh
.venv/bin/python -m uvicorn jobmitra.main:app --host 127.0.0.1 --port 8000
```

Port 8765 belongs to the optional disposable preview. Use port 8000 for Windows data.

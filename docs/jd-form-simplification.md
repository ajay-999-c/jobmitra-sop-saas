# JD form simplification

The create/edit form uses one optional general-skills field and INR salary inputs.
Commas/newlines split skills; blank entries are removed, internal whitespace is
collapsed, and case-insensitive duplicates retain the first spelling. General skills
are not mandatory criteria. Existing required/preferred/specific skills and specific
experience remain intact, shown as read-only context, and omitted from form patches.

## Database prerequisite

Revision `0005_jd_general_skills` adds only `job_requirements.general_skills`
(`text[] NOT NULL DEFAULT '{}'`) and a constraint against null array elements.
Existing columns and values are untouched. The existing schema has no safe place
for unclassified skills: neither required/preferred criteria nor ATS suggestions
represent this employee-entered information.

This migration has been applied only to disposable local test databases.
Windows migration requires separate approval before deploying this application
version. The ORM expects the new column, so do not deploy the changed application
against revision 0004. Downgrading removes newly entered general skills.

New API-created JDs default to INR; the currency column and existing API support
remain. Historical non-INR or unspecified currencies are read-only in this INR
form and are neither converted nor relabeled. Historical Unknown salary periods
are preserved. New forms offer Monthly/Annual; changing between them converts
entered amounts by 12, rounded to two decimal places. Selecting a period from
Unknown does not infer or convert an amount.

ATS JSON remains a separate draft/reviewed/stale workflow. Saving suggestions or
marking them reviewed never copies them into company-confirmed criteria. Employee
review and manual entry are still required. No AI integrations or candidate parsing
changes were introduced.

## Verification

- Read-only inspection confirmed live salary/skill column definitions.
- 87 JD/candidate regression tests passed in isolated PostgreSQL, including migration
  preservation, general-skill normalization, legacy criteria/currency preservation,
  ATS isolation, and unrelated-field preservation.
- Browser creation and editing passed; persisted data was checked after reload.
- Monthly/Annual conversion and desktop/mobile overflow checks passed.
- Ruff, JavaScript syntax, and whitespace checks passed.
- Screenshots: `output/playwright/jd-create-desktop.png`, `jd-create-mobile.png`,
  `jd-edit-desktop.png`, and `jd-edit-mobile.png`.

No Windows schema/records were modified. No commit or push was made.

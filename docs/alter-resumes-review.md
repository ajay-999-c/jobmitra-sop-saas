# Alter Resumes integration — local review

Route: `/alter-resumes`. Main navigation places Alter Resumes immediately after Staff, with the shared active-state and responsive navigation. No separate application, iframe, production server or port.

## Source and implementation

Adapted the supplied `Jobmitra_Resume_Studio_v1.2.html` from Downloads. Its reusable prompt, local text/JSON normalization, JSON/TXT import, editable review, advanced editor, preview, copy helpers and original OOXML/ZIP DOCX generator are retained. The embedded original logo is retained byte-for-byte in exported DOCX. The standalone header is removed.

Changed/added files:

- `src/jobmitra/main.py`: register the router and module static mount.
- `src/jobmitra/modules/alter_resumes/__init__.py`, `router.py`: one read-only page route using the existing render helper; reads shared staff choices only.
- `src/jobmitra/templates/stage2/base.html`: one navigation item after Staff. The previously implemented official-logo change remains intact.
- `src/jobmitra/templates/alter_resumes/studio.html`: supplied workspace within the shared shell; private-download wording explicitly says no database registration occurs.
- `src/jobmitra/static/alter_resumes/studio.css`: scoped source styles and route-local print/mobile overrides.
- `src/jobmitra/static/alter_resumes/studio.mjs`: extracted original functionality; external module complies with existing CSP; unapplied advanced edits disable exports; editing private fields refreshes public preview.
- `src/jobmitra/static/alter_resumes/privacy.mjs`: common public-output filter applied to preview, DOCX, shareable JSON and print. Removes known private values and recognizable contacts/residential text from nested free text; internal review notes are excluded from public JSON. Does not mutate private candidate data. Employees should still review free text, especially unusual or obfuscated contact wording.
- `tests/test_alter_resumes.py`: read-only page/nav/CSP/assets checks without database access.
- `tests/test_resume_studio_privacy.mjs`: nested privacy filtering, names/dates preservation and private-data immutability.

No Candidate, JD or Company services changed in this task. Existing unrelated local changes remain untouched. No tables, model changes or Alembic migration files added.

## Verification

- Python shell test: 1 passed. Node privacy tests: 2 passed. Ruff, JavaScript syntax and diff whitespace checks passed. Existing Starlette/httpx deprecation warning remains.
- Browser: sample preview; candidate name; JSON and TXT imports; Copy Prompt and Copy Prompt + Resume Text; edited title; advanced edits and apply; all three downloads; private registration contacts separate from public content.
- Exported synthetic DOCX: valid ZIP with readable XML parts, original embedded logo, candidate name and reviewed professional title. Parsed successfully using macOS textutil's Word-document reader. Microsoft Word itself was not installed/tested.
- Scanned all DOCX XML parts and public JSON for the synthetic email, international phone numbers, residential city/state, street address and social URLs: absent. Private JSON retains its candidate email, phone, city/state and links.
- Browser PDF/print: only public resume content visible; no global nav, attribution, source fields, controls, private card or local-download notice. Generated PDF and print screenshot retained locally.
- Desktop 1440×1100 and mobile 390×844 checked visually; no horizontal document overflow, vertical scrolling and two-column/stacked layout work.
- Shared Companies, JD Tracking, Candidate Desk and Alter Resumes links opened successfully in the same app. No mutation requests or JavaScript errors during workflow verification; the disposable candidate directory remained empty.

Browser verification used the existing unified FastAPI app against disposable local PostgreSQL, with empty tables initialized from existing metadata. No Alembic commands, Windows database access or production data were used. The temporary preview was shut down after verification.

Artifacts (ignored by Git) in `output/playwright/`:

- `alter-resumes-desktop.png`, `alter-resumes-mobile.png`, `alter-resumes-mobile-preview.png`, `alter-resumes-print.png`
- `studio-private.json`, `studio-public.json`, `studio-resume.docx`, `studio-resume.pdf` (synthetic inputs only)

No automatic database registration, external AI requests, resume-file modifications, commit or push.

# Approved single-page Company Terms template

## Sources and scope

The retained approved Word reference controls the wording, run-level bold
formatting, numbering, margins and sign-off. The supplied PDF controls visual
comparison. The project-root Word file with the `(1)` suffix is byte-identical
to the Downloads Word file named in the request. Both originals remain unchanged.

Canonical, unchanged reference copies are tracked at:

- `docs/references/proposal-terms/approved-single-page.docx` — SHA-256
  `564092628abd2176a4b30c06faca7850829b22d48d09a6e0df650f3068430b66`.
- `docs/references/proposal-terms/approved-single-page.pdf` — SHA-256
  `c701249aaefe349e1826863ab7934f19f086ac4e9edb91b8f232128dc4e25cc6`.

These are the explicitly approved unsigned template assets, reviewed for empty
acceptance fields, document metadata and external relationships. They contain
the reference company name and public consultant details, with no private
recipient details, filled signatures, attachments or external relationships.
Generated proposal PDFs, runtime records and browser evidence remain ignored.

Only the existing `proposal_pdf.render()` presentation and its approved terms
source changed. New snapshots identify PDF renderer version 3 and the approved
Word hash. No database migration or second proposal-generation system was added.

## Reproduced layout

- A4, approximately 51pt left/right margins, source logo at 116.2 × 36.8pt.
- Centered 18pt bold Terms & Conditions title; body 11.5pt with 15.2pt leading.
- Exact introduction and ten clauses transcribed from Word runs, including
  their bold ranges and punctuation. No independently rewritten legal text.
- Dynamic company name in the introduction and acceptance heading. Clause 1
  substitutes only 6% / 21 days or 8.33% / 30 days, retaining annual CTC wording.
- 7pt clause spacing and consistent hanging numbering; no old summary table,
  additional closing paragraph, separate acknowledgement, date or seal field.
- With regards and Accepted by share the same first baseline. Vishal Agrawal
  follows immediately at 15pt leading, then CEO and e - Friend Solutions India.
- Acceptance contains Authorized Person Name, Designation and one signature
  box approximately 237.7 × 72.8pt. No consultant signature box is added.
- Reference/date remain in the approved top-right location and are dynamic.

The Word style names Arial; the approved PDF embeds Liberation Sans. Matching,
unchanged Liberation Sans 2.1.5 regular/bold fonts are bundled with their SIL
Open Font License and copyright notices. Provenance and checksums are recorded
in `src/jobmitra/static/ats_v2/proposal-assets/README.md`. No system font,
runtime download, new Python dependency or Windows configuration is required.

The original JPEG logo, Inter font assets and their license remain retained.
The new PNG is the exact image from the approved Word reference.

## Focused verification — 26 November 2026

14 focused Python checks passed: source/run fidelity, supplied-reference hashes,
normal and very long names, A4 geometry and sign-off alignment, fee arithmetic,
private storage/download checksums, historical retry preservation, signed
versions, Email context, failed-publish rollback/concurrency, stale status and
HTML escaping/request limits. Both fee variants were also exercised against
disposable PostgreSQL schemas. Ruff, Python syntax, JSON parsing and Git
whitespace checks passed; the full suite was not run.

The actual Companies -> Prepare Proposal workflow on isolated port 8899 generated
and downloaded these review files:

| Canonical test company | Fee / salary days | Pages | Review artifact |
| --- | --- | --- | --- |
| Kedia Traders | 6% / 21 | 1 | `output/pdf/Jobmitra-Terms-Kedia-Traders-6pct.pdf` |
| Nimar Motors | 8.33% / 30 | 1 | `output/pdf/Jobmitra-Terms-Nimar-Motors-8_33pct.pdf` |
| International Automotive Components Manufacturing and Distribution Services Private Limited | 6% / 21 | 1 | `output/pdf/Jobmitra-Terms-Long-Company-6pct.pdf` |

All three stored files match their browser downloads byte-for-byte and match
PostgreSQL `pdf_sha256`/`pdf_size`. All ten clauses and the correct company/fee
remain present. Rendered pages were opened and inspected; no clipping,
overlapping content or missing glyphs was found. The normal sign-off baseline
is 593pt from the page top; the long-name case naturally shifts it to 608.2pt,
with both headings still aligned and the signature box retaining its full size.

A matching-data Kedia 6% render was compared visually with the approved PDF.
Automated anchor checks compare title, sign-offs, authorized name, designation
and signature positions within 0.25pt of the reference. Line wrapping and bold
ranges match; dynamic references/date and company/fee substitutions are expected.
The original reference and generated page images remain local QA artifacts.

Prepare Email was opened from both new normal-name versions. It retains the
original branded composer, canonical company context and selected PDF download.
The deliberately empty test recipient is not fabricated. No email was sent and
no Sent/Accepted status was recorded. The browser session had zero console
errors or warnings. Email Studio files and the existing Email API subject remain
unchanged.

## History and data safety

Verification uses only the Unix-socket-only local PostgreSQL test cluster,
schema `jobmitra_v12_dev_terms_4a66f2f9`, and private storage under
`runtime/proposal-terms-preview/proposals`. Its three company records were
created for this test. No office PostgreSQL schema, production SQLite database,
existing candidate/company record or original document store was changed.

A real version-2, two-page PDF was generated in that isolated schema before the
renderer changed. After all three new versions, its complete public metadata
was unchanged and its historical API download retained SHA-256
`7443eaf1e71d794400a58faf4fea10569c780ff8a9051de98a8cbdf361566b60`.
The isolated store contains four preserved proposal versions and zero status
events. No historical PDF was overwritten or regenerated. A separate focused
test also verifies retrying an old request never invokes the new renderer.

`proposal_documents.py`, proposal APIs, reference generation, proposal history,
signed upload/download, document hashes, status evidence, WindowsStore, ACL/
ownership rules, resume storage, diagnostics, ENV files and NSSM are unchanged.
The approved V12 UI and original Email Studio source hashes remain unchanged.

## Deviations and limits

All three requested examples remain single-page A4. An extreme stress name,
well beyond the normal examples, may move the final clause and complete
signature block together to a second A4 page. It preserves wording, font size,
alignment and handwriting space; it never clips or silently shrinks the text.
Both stress pages were rendered and inspected. Native Windows execution remains
a deployment check; no Windows storage or service changes are part of this task.

## Files in the checkpoint

- `src/jobmitra/modules/ats_v2/proposal_pdf.py`
- `src/jobmitra/modules/ats_v2/proposal_terms.json`
- `src/jobmitra/static/ats_v2/proposal-assets/README.md`
- `src/jobmitra/static/ats_v2/proposal-assets/LiberationSans-Regular.ttf`
- `src/jobmitra/static/ats_v2/proposal-assets/LiberationSans-Bold.ttf`
- `src/jobmitra/static/ats_v2/proposal-assets/OFL-Liberation.txt`
- `src/jobmitra/static/ats_v2/proposal-assets/terms-logo.png`
- `docs/references/proposal-terms/approved-single-page.docx`
- `docs/references/proposal-terms/approved-single-page.pdf`
- `tests/test_v12_proposal_pdf.py`
- This report.

The checkpoint is local only. Do not push until the user reviews the generated PDFs.

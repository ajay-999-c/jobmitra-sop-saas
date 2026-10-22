# Foundit candidate intake release

Adds Candidate Desk → Foundit Paste, local deterministic parsing, editable grouped review, phone/email duplicate checks and explicit create/selective version-checked update. Candidate domain selectors reuse the existing catalog. No external AI, Foundit scraping or WhatsApp integration.

This release needs no schema migration. It targets the existing 0005_jd_general_skills database. Pending JD company/catalog work and 0006_jd_catalog_links are excluded from this release.

Name, contact, role, total experience, domain/subdomain, salary, notice, skills, complete qualification wording, preferred locations and explicit relocation values use existing candidate columns. Employer/industry, full employment history, separate institution/year and original paste remain editable draft-only fields. Download the reviewed draft to retain them. Proposed nullable JSONB candidates.foundit_details storage requires separate approval; no migration has been created for it.

Parser tests cover footer contacts, incomplete numbers, explicit experience conversions, current/past jobs, source-label cleanup and three synthetic profile variations. Prior isolated workflow verification covered creation, selective updates, duplicate/stale-version rejection, zero-write repeated parsing and unchanged document bytes. Desktop/mobile browser verification completed Parse → Edit → Duplicate Check → Save, followed by explicit linking and a role-only update. Screenshots and synthetic runtime artifacts are excluded from Git.

Deployment: stop employee writes and the existing backend; preserve .env, document storage and the existing startup command/LAN binding. Require clean Git status on main, fetch origin/main, verify the approved commit is on origin/main and that the update is fast-forward, then merge that exact commit with --ff-only. Run uv sync --frozen using the established Windows environment and restart with the previously working command/service. Do not run Alembic for this release. Check /health/live, /health/ready, Foundit parsing and candidate navigation before reopening writes.

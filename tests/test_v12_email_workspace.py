"""Email entry points are read-only and retain the original approved tools."""

import re
from pathlib import Path

from test_v12_postgres_backend import snapshot

pytest_plugins = ["test_v12_creation_failures"]

ROOT = Path(__file__).resolve().parents[1]


def test_office_email_workspace_and_all_manual_tools_are_read_only(office, pg_store):
    before = snapshot(pg_store[0][0])
    for query in ["", "?tool=updates", "?tool=submission", "?tool=proposal"]:
        response = office.get("/workspace-v12/email" + query)
        assert response.status_code == 200
        assert 'data-section="email"' in response.text
        buttons = re.findall(r'<button id="unified\w+Tab"[^>]*>(.*?)</button>', response.text)
        assert buttons == ["Companies", "Candidate Desk", "JD Tracking", "Email"]
        assert 'href="/workspace-v12/email?tool=proposal"' in response.text
        assert "stage2/base.html" not in response.text
    assert office.get("/api/v12/access").json()["office_lan"]
    for route, name in [
        ("/email/proposal", "Jobmitra_Company_Proposal_Final.html"),
        ("/email/updates", "Jobmitra_Email_Studio_Final_Management_Confirmed.html"),
        ("/email/submission", "Jobmitra_candidate_submission_final (1).html"),
    ]:
        assert office.get(route).content == (ROOT / name).read_bytes()
    assert snapshot(pg_store[0][0]) == before


def test_fourth_workspace_does_not_change_clean_jd_assets_or_embedded_registry():
    source = (ROOT / "Jobmitra_Unified_Workspace_V12_Companies_Integrated (1).html").read_text()
    generated = (ROOT / "src/jobmitra/static/ats_v2/approved.mjs").read_text()
    pattern = r'const EMAIL_STUDIO_DOCUMENT=("(?:\\.|[^"\\])*");'
    assert re.search(pattern, source)[1] == re.search(pattern, generated)[1]
    assert "installEmailWorkspace(EMAIL_STUDIO_DOCUMENT)" in generated
    assert "installContextualEmail(native,EMAIL_STUDIO_DOCUMENT,pipelineEmailContext)" in generated
    assert 'data-email-profile="${escapeHTML(c.id)}"' in generated
    assert 'data-email-job="${escapeHTML(r.jobId)}"' in generated

"""Resume Studio shell checks without a database connection or migration."""

from contextlib import nullcontext

from fastapi.testclient import TestClient

from jobmitra.core import pages
from jobmitra.core.config import Settings
from jobmitra.core.database import get_session
from jobmitra.main import create_app


def test_studio_uses_shared_nav_strict_csp_and_no_database_writes(monkeypatch):
    class ReadOnlySession:
        def begin_nested(self):
            return nullcontext()

    session = ReadOnlySession()
    monkeypatch.setattr(pages, "list_staff", lambda received: [] if received is session else None)
    config = Settings(
        _env_file=None,
        db_host="127.0.0.1",
        db_name="unused",
        db_user="unused",
        db_password="synthetic-unused",
    )
    app = create_app(config)
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)  # No lifespan/database engine needed for this read-only shell.
    response = client.get("/alter-resumes")
    assert response.status_code == 200
    html = response.text
    nav = html.split('<nav class="global-nav"')[1].split("</nav>")[0]
    assert (
        nav.index('href="/staff"') < nav.index('href="/alter-resumes"') < nav.index('href="/tasks"')
    )
    assert 'href="/alter-resumes" aria-current="page"' in nav
    for route in ["/companies", "/requirements", "/candidate-desk"]:
        assert f'href="{route}"' in nav
    assert 'class="appbar"' not in html and "<iframe" not in html
    assert 'style="' not in html
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    for name in ["studio.css", "studio.mjs", "privacy.mjs"]:
        assert client.get("/static/alter-resumes/" + name).status_code == 200
    assert "No candidate record is created or updated." in html
    assert "Download Private Registration JSON" in html
    assert "Shareable Resume JSON" in html
    assert client.post("/alter-resumes").status_code == 405

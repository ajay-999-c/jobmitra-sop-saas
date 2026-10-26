"""Verbatim Email responses and navigation, with database connections forbidden."""

import hashlib
from unittest.mock import Mock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from jobmitra.core.config import Settings
from jobmitra.core.pages import templates
from jobmitra.main import create_app
from jobmitra.modules.email_studio.router import SUBMISSION_FILE, UPDATES_FILE


@pytest.fixture
def client(monkeypatch):
    engine = Mock()
    engine.connect.side_effect = AssertionError("Email must never connect to a database")
    monkeypatch.setattr("jobmitra.main.build_engine", lambda _: engine)
    monkeypatch.setattr(
        "jobmitra.core.pages.list_staff", Mock(side_effect=AssertionError("No staff query"))
    )
    settings = Settings(
        _env_file=None,
        db_host="invalid.example",
        db_name="unused",
        db_user="unused",
        db_password="unused",
    )
    app = create_app(settings)

    @app.get("/test-shell")
    def shell(request: Request):
        return templates.TemplateResponse(
            request=request, name="stage2/base.html", context={"staff": []}
        )

    with TestClient(app) as browser:
        yield browser
    engine.connect.assert_not_called()


@pytest.mark.parametrize(
    "route,path", [("/email/updates", UPDATES_FILE), ("/email/submission", SUBMISSION_FILE)]
)
def test_original_bytes_unchanged_and_get_only(client, route, path):
    original = path.read_bytes()
    response = client.get(route)
    assert response.status_code == 200
    assert response.content == original
    assert hashlib.sha256(response.content).digest() == hashlib.sha256(original).digest()
    assert response.headers["content-type"].startswith("text/html")
    assert "attachment" not in response.headers.get("content-disposition", "")
    assert "content-security-policy" not in response.headers  # Do not alter original behavior.
    assert client.post(route, json={"candidate": "Synthetic"}).status_code == 405


def test_landing_page_and_single_navbar_link(client):
    response = client.get("/email", follow_redirects=False)
    assert response.status_code == 200
    assert 'href="/email/updates"' in response.text
    assert 'href="/email/submission"' in response.text
    assert "Candidate Updates" in response.text
    assert "Candidate Submission" in response.text
    shell = client.get("/test-shell").text
    assert shell.count('href="/email"') == 1
    assert 'href="/email/updates"' not in shell
    assert 'href="/email/submission"' not in shell
    for route in ["/companies", "/requirements", "/candidate-desk"]:
        assert f'href="{route}"' in shell
    assert 'id="recording-as"' in shell

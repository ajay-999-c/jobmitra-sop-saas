"""Only content-versioned public assets receive immutable caching."""

import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jobmitra.core.v12_assets import V12Assets


def test_versioned_assets_and_unversioned_helpers_revalidate(tmp_path):
    blob = b"export const value = 1;\n"
    (tmp_path / "component.mjs").write_bytes(blob)
    app = FastAPI()
    app.mount("/static/ats-v2", V12Assets(directory=tmp_path))
    with TestClient(app) as client:
        path = "/static/ats-v2/component.mjs"
        bare = client.get(path)
        assert bare.content == blob
        assert bare.headers["cache-control"] == "public, max-age=0, must-revalidate"
        version = hashlib.sha256(blob).hexdigest()[:16]
        versioned = client.get(path + "?v=" + version)
        assert "immutable" in versioned.headers["cache-control"]
        assert client.get(path, headers={"If-None-Match": bare.headers["etag"]}).status_code == 304
        assert "immutable" not in client.get(path + "?v=wrong").headers["cache-control"]

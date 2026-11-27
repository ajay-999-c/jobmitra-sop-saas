"""Cache public V12 assets by content; never caches private pages/API/documents."""

import hashlib
from pathlib import Path
from urllib.parse import parse_qs

from fastapi.staticfiles import StaticFiles


class V12Assets(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # Bare helper imports revalidate; generated URLs carry an exact content hash.
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
        version = parse_qs(scope.get("query_string", b"").decode("ascii", "ignore")).get("v", [])
        if version:
            filename, stat = self.lookup_path(path)
            if stat and Path(filename).is_file():
                digest = hashlib.sha256(Path(filename).read_bytes()).hexdigest()[:16]
                if version == [digest]:
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

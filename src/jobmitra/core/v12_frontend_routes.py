"""Only verified frontend equivalents redirect in explicit V12 mode; APIs are untouched."""

import re

from starlette.responses import RedirectResponse


class V12FrontendRoutes:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and self.settings.unified_v12_enabled
        ):
            path = scope["path"].rstrip("/") or "/"
            target = {
                "/": "/workspace-v12/jobs",
                "/overview": "/workspace-v12/jobs",
                "/companies": "/workspace-v12/companies",
                "/candidate-desk": "/workspace-v12/candidates",
                "/candidates": "/workspace-v12/candidates?section=candidates",
                "/candidates/new": "/workspace-v12/candidates?register=1",
                "/candidates/foundit-import": "/workspace-v12/candidates?section=foundit",
                "/candidate-search-v2": "/workspace-v12/candidates",
                "/jd-workspace-v2": "/workspace-v12/jobs",
                "/requirements": "/workspace-v12/jobs",
                "/office-visits": "/workspace-v12/candidates?section=visits",
                "/job-search-requests": "/workspace-v12/candidates?section=requests",
            }.get(path)
            match = re.fullmatch(r"/ats-v2/candidates/(\d+)", path)
            if match:
                target = "/workspace-v12/candidates?section=candidates&candidate_id=" + match[1]
            if target:
                return await RedirectResponse(target, status_code=303)(scope, receive, send)
        return await self.app(scope, receive, send)

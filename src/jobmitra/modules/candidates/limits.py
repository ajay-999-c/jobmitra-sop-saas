"""Bound Candidate Desk JSON bodies before FastAPI parses them."""

from starlette.responses import JSONResponse


class CandidateJSONLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        guarded = scope["type"] == "http" and scope.get("path", "").startswith(
            ("/api/candidates", "/api/job-search-requests", "/api/domains", "/api/subdomains")
        )
        if not guarded or not headers.get(b"content-type", b"").lower().startswith(
            b"application/json"
        ):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 300 * 1024:
                return await JSONResponse(
                    {"detail": "JSON request exceeds 300 KiB."}, status_code=413
                )(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

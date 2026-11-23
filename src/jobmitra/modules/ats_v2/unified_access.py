"""Opt-in operator capability sessions; never claim an individually verified login.

The actor name remains a declared snapshot. Production needs an approved identity
provider/cutover; no operator or supervisor capability exists by default.
"""

import hashlib
import hmac
import time

from .common import AtsError
from .database import schema_version

COOKIE = "jobmitra_v12_access"


def _secret(settings, role):
    value = (
        settings.unified_v12_supervisor_token
        if role == "SUPERVISOR_TOKEN"
        else settings.unified_v12_operator_token
    )
    return value.get_secret_value() if value else None


def issue(settings, token):
    for role in ("SUPERVISOR_TOKEN", "OPERATOR_TOKEN"):
        secret = _secret(settings, role)
        if secret and hmac.compare_digest(secret, token):
            payload = f"{role}:{int(time.time()) + 8 * 3600}"
            signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
            return payload + ":" + signature
    raise AtsError("Operator access is unavailable or the access key is invalid.", 403)


def access(request, supervisor=False):
    settings = request.app.state.settings
    if settings.unified_v12_local_direct_editing:
        # LocalPreviewGuard checks peer, socket, Host and proxy headers first.
        return "LOCAL_DEVELOPMENT"
    raw = request.cookies.get(COOKIE, "")
    try:
        role, expires, signature = raw.split(":")
        secret = _secret(settings, role) if role in {"OPERATOR_TOKEN", "SUPERVISOR_TOKEN"} else None
        payload = role + ":" + expires
        expected = hmac.new((secret or "").encode(), payload.encode(), hashlib.sha256).hexdigest()
        if secret and int(expires) > time.time() and hmac.compare_digest(expected, signature):
            if not supervisor or role == "SUPERVISOR_TOKEN":
                return role
    except (ValueError, TypeError):
        pass
    raise AtsError(
        "Unlock workspace editing with an authorized access key.", 403, "OPERATOR_ACCESS_REQUIRED"
    )


def guard_write(request):
    if (
        request.method not in {"POST", "PUT", "PATCH", "DELETE"}
        or request.url.path == "/api/v12/access"
    ):
        return
    engine = getattr(request.app.state, "ats_v2_engine", None)
    if engine is not None:
        with engine.connect() as conn:
            version = schema_version(conn)
        if version == 3:
            access(request)
            if (
                not request.url.path.startswith("/api/v12/")
                or request.url.path.startswith("/api/v12/approved/")
            ) and not request.headers.get("Idempotency-Key"):
                raise AtsError("V3 mutations require an Idempotency-Key UUID.")

"""Transactional V3 retry receipts, separate from recruitment milestones.

Receipts contain a request hash and canonical resource ID, never a copied email
send/selection. They are appended in the same transaction as the operation.
"""

import hashlib
import json
from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import text

from .common import AtsError
from .database import schema_version

request_key = ContextVar("ats_request_key", default=None)


def set_key(value):
    if value:
        try:
            value = str(UUID(value))
        except ValueError:
            raise AtsError("Idempotency-Key must be a UUID.") from None
    return request_key.set(value)


def digest(scope, data):
    return hashlib.sha256(
        json.dumps([scope, data], sort_keys=True, default=str).encode()
    ).hexdigest()


def replay(conn, scope, data):
    key = request_key.get()
    if not key or schema_version(conn) != 3:
        return None
    row = conn.execute(
        text(
            "SELECT payload_json FROM recruitment_events WHERE "
            "json_extract(payload_json,'$.idempotency_key')=:key"
        ),
        {"key": key},
    ).first()
    if not row:
        return None
    payload = json.loads(row[0])
    if payload.get("request_fingerprint") != digest(scope, data):
        raise AtsError("This request key was used for a different operation.", 409)
    return payload["resource_id"]


def record(conn, scope, data, resource_id, *, candidate_id=None, job_id=None, details=None):
    key = request_key.get()
    if key and schema_version(conn) == 3:
        conn.execute(
            text(
                "INSERT INTO recruitment_events(candidate_id,job_id,event_type,payload_json) "
                "VALUES(:candidate,:job,'REQUEST_COMPLETED',:payload)"
            ),
            {
                "candidate": candidate_id,
                "job": job_id,
                "payload": json.dumps(
                    {
                        "idempotency_key": key,
                        "request_fingerprint": digest(scope, data),
                        "resource_id": resource_id,
                        "scope": scope,
                        **({"details": details} if details is not None else {}),
                    }
                ),
            },
        )

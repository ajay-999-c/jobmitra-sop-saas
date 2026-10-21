"""Stage 2 transaction errors, attribution and office-calendar helpers."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from jobmitra.core.database import get_session


class WorkflowError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def workflow_session(response: Response, session: Annotated[Session, Depends(get_session)]):
    response.headers["Cache-Control"] = "no-store"
    try:
        yield session
    except WorkflowError as error:
        session.rollback()
        raise HTTPException(error.status, str(error)) from None
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "This change conflicts with related records. Reload and retry."
        ) from None
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            503, "Database unavailable or Stage 2 migration not yet applied."
        ) from None


Database = Annotated[Session, Depends(workflow_session)]


def same_origin(request: Request):
    origin = request.headers.get("origin")
    if request.headers.get("x-jobmitra-ui") != "1" or (
        origin and origin != f"{request.url.scheme}://{request.url.netloc}"
    ):
        raise HTTPException(403, "Submit changes from this application.")


def office_today(timezone, now=None):
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone)).date()


def optional_uuid(value):
    try:
        return UUID(value) if value else None
    except ValueError:
        raise WorkflowError("Invalid employee filter.") from None


def json_value(value):
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return value.isoformat() if hasattr(value, "isoformat") else str(value)

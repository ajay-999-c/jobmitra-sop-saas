from collections.abc import Iterator
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from jobmitra.core.database import get_session
from jobmitra.modules.companies import repository, service
from jobmitra.modules.companies.schemas import (
    CompanyDetail,
    CompanyInput,
    CompanyUpdate,
    CompanyVersion,
)

MODULE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(MODULE_DIR / "templates"))
router = APIRouter(tags=["Companies"])


class CompanyAssets(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


def company_session(
    response: Response, session: Annotated[Session, Depends(get_session)]
) -> Iterator[Session]:
    response.headers["Cache-Control"] = "no-store"
    try:
        yield session
    except service.NotFound:
        raise HTTPException(404, "Company not found. Refresh the directory.") from None
    except service.StaleEdit:
        session.rollback()
        raise HTTPException(
            409, "Someone changed this company. Reload its details before saving or deleting."
        ) from None
    except service.InvalidContact:
        session.rollback()
        raise HTTPException(422, "Contact IDs must be unique and belong to this company.") from None
    except IntegrityError as error:
        session.rollback()
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        message = (
            "A company with this name already exists."
            if constraint == "uq_companies_company_name_key"
            else "This change conflicts with existing records. No changes were saved."
        )
        raise HTTPException(409, message) from None
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Database unavailable. Please try again.") from None


Database = Annotated[Session, Depends(company_session)]


def same_origin(request: Request):
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("x-jobmitra-ui") != "1" or (origin and origin != expected):
        raise HTTPException(403, "Company changes must be submitted from this application.")


@router.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/companies", status_code=303, headers={"Cache-Control": "no-store"})


@router.get("/companies", response_class=HTMLResponse)
def company_directory(request: Request, session: Database):
    return templates.TemplateResponse(
        request=request,
        name="companies/directory.html",
        context={"companies": repository.directory(session)},
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'"
            ),
        },
    )


@router.get("/api/companies")
def directory_snapshot(session: Database) -> list[dict[str, str]]:
    return repository.directory(session)


@router.get("/api/companies/{company_id}", response_model=CompanyDetail)
def company_detail(company_id: UUID, session: Database):
    return service.detail(session, service.require_company(session, company_id))


@router.post(
    "/api/companies",
    response_model=CompanyDetail,
    status_code=201,
    dependencies=[Depends(same_origin)],
)
def create_company(data: CompanyInput, session: Database):
    return service.write(session, data)


@router.put(
    "/api/companies/{company_id}",
    response_model=CompanyDetail,
    dependencies=[Depends(same_origin)],
)
def edit_company(company_id: UUID, data: CompanyUpdate, session: Database):
    return service.write(session, data, company_id)


@router.delete("/api/companies/{company_id}", status_code=204, dependencies=[Depends(same_origin)])
def delete_company(company_id: UUID, data: CompanyVersion, session: Database):
    service.delete(session, company_id, data.updated_at)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})

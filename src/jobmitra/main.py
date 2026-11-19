from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from jobmitra.core.config import Settings, get_settings
from jobmitra.core.database import build_engine, check_database
from jobmitra.core.pages import PACKAGE_DIR, templates
from jobmitra.modules.alter_resumes.router import router as alter_resumes_router
from jobmitra.modules.ats_v2.database import build_ats_engine
from jobmitra.modules.ats_v2.database import validate as validate_ats_database
from jobmitra.modules.ats_v2.router import AtsBodyLimit
from jobmitra.modules.ats_v2.router import router as ats_v2_router
from jobmitra.modules.candidates.limits import CandidateJSONLimit
from jobmitra.modules.candidates.resumes import router as resumes_router
from jobmitra.modules.candidates.router import router as candidates_router
from jobmitra.modules.companies.router import MODULE_DIR, CompanyAssets
from jobmitra.modules.companies.router import router as companies_router
from jobmitra.modules.email_studio.router import router as email_studio_router
from jobmitra.modules.jobs.router import router as jobs_router
from jobmitra.modules.resume_processing.router import ResumeBodyLimit
from jobmitra.modules.resume_processing.router import router as resume_processing_router
from jobmitra.modules.staff.router import router as staff_router
from jobmitra.modules.worklog.router import router as worklog_router


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = build_engine(config)
        app.state.ats_v2_engine = None
        ats_engine = None
        try:
            if config.ats_v2_enabled and config.ats_v2_database:
                try:
                    path = config.ats_v2_database.expanduser().resolve()
                    if path.is_file():
                        ats_engine = build_ats_engine(path)
                        validate_ats_database(ats_engine)
                        app.state.ats_v2_engine = ats_engine
                except (SQLAlchemyError, RuntimeError, OSError, ValueError):
                    # An unavailable new store must not stop the legacy application.
                    if ats_engine is not None:
                        ats_engine.dispose()
                    ats_engine = None
            yield
        finally:
            if ats_engine is not None:
                ats_engine.dispose()
            app.state.engine.dispose()

    app = FastAPI(title="Jobmitra", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CandidateJSONLimit)
    app.add_middleware(ResumeBodyLimit, max_bytes=config.resume_max_bytes)
    app.add_middleware(AtsBodyLimit, max_bytes=config.resume_max_bytes)
    app.mount(
        "/static/companies",
        CompanyAssets(directory=str(MODULE_DIR / "static")),
        name="company-static",
    )
    app.include_router(companies_router)
    app.state.settings = config
    app.mount(
        "/static/stage2",
        CompanyAssets(directory=str(PACKAGE_DIR / "static" / "stage2")),
        name="stage2-static",
    )
    app.include_router(candidates_router)
    app.include_router(resumes_router)
    app.mount(
        "/static/candidates",
        CompanyAssets(directory=str(PACKAGE_DIR / "static" / "candidates")),
        name="candidate-static",
    )
    app.include_router(alter_resumes_router)
    app.mount(
        "/static/alter-resumes",
        CompanyAssets(directory=str(PACKAGE_DIR / "static" / "alter_resumes")),
        name="alter-resumes-static",
    )
    app.include_router(email_studio_router)
    app.include_router(resume_processing_router)
    app.include_router(staff_router)
    app.include_router(jobs_router)
    app.include_router(worklog_router)
    app.mount(
        "/static/ats-v2",
        CompanyAssets(directory=str(PACKAGE_DIR / "static" / "ats_v2")),
        name="ats-v2-static",
    )
    app.include_router(ats_v2_router)

    @app.exception_handler(HTTPException)
    async def portal_error(request: Request, error: HTTPException):
        if (
            error.status_code == 503
            and request.method == "GET"
            and (
                not request.url.path.startswith(("/api/", "/health/", "/static/"))
                and "/download" not in request.url.path
            )
        ):
            return templates.TemplateResponse(
                request=request,
                name="stage2/unavailable.html",
                status_code=503,
                context={"staff": []},
                headers={"Cache-Control": "no-store"},
            )
        return await http_exception_handler(request, error)

    @app.get("/health/live", tags=["Health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"])
    def ready(request: Request):
        try:
            check_database(request.app.state.engine)
        except (SQLAlchemyError, RuntimeError):
            # Never return driver errors, URLs or credentials to clients.
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ok", "database": "connected"}

    return app


app = create_app()

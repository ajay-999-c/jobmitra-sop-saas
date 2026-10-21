from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from jobmitra.core.config import Settings, get_settings
from jobmitra.core.database import build_engine, check_database
from jobmitra.core.pages import PACKAGE_DIR
from jobmitra.modules.companies.router import MODULE_DIR, CompanyAssets
from jobmitra.modules.companies.router import router as companies_router
from jobmitra.modules.jobs.router import router as jobs_router
from jobmitra.modules.staff.router import router as staff_router
from jobmitra.modules.worklog.router import router as worklog_router


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = build_engine(config)
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(title="Jobmitra", version="0.1.0", lifespan=lifespan)
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
    app.include_router(staff_router)
    app.include_router(jobs_router)
    app.include_router(worklog_router)

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

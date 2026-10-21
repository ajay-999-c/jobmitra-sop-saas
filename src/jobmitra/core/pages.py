from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from jobmitra.modules.staff.repository import list_staff

PACKAGE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(
    directory=[str(PACKAGE_DIR / "templates"), str(PACKAGE_DIR / "modules/companies/templates")]
)
templates.env.filters["local_time"] = lambda value, tz: (
    value.astimezone(ZoneInfo(tz)).strftime("%d %b %Y %H:%M") if value else "—"
)


def render(request, session, name, *, template_group="stage2", **context):
    try:
        with session.begin_nested():
            staff = list_staff(session)
    except SQLAlchemyError:
        staff = []
    return templates.TemplateResponse(
        request=request,
        name=f"{template_group}/{name}.html",
        context={
            "staff": staff,
            "office_timezone": request.app.state.settings.office_timezone,
            **context,
        },
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'"
            ),
        },
    )

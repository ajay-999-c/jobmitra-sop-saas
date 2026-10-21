from uuid import UUID

from fastapi import APIRouter, Depends, Request

from jobmitra.core.pages import render
from jobmitra.core.workflow import Database, same_origin
from jobmitra.modules.staff import repository
from jobmitra.modules.staff.schemas import StaffCreate, StaffPatch, StaffRead
from jobmitra.modules.staff.service import StaffService

router = APIRouter(tags=["Staff"])


@router.get("/api/staff", response_model=list[StaffRead])
def list_staff(session: Database, active_only: bool = False):
    return repository.list_staff(session, active_only=active_only)


@router.post(
    "/api/staff", response_model=StaffRead, status_code=201, dependencies=[Depends(same_origin)]
)
def create_staff(data: StaffCreate, session: Database):
    return StaffService(session).add_staff(data)


@router.patch(
    "/api/staff/{staff_id}", response_model=StaffRead, dependencies=[Depends(same_origin)]
)
def patch_staff(staff_id: UUID, data: StaffPatch, session: Database):
    return StaffService(session).patch_staff(staff_id, data)


@router.get("/staff", include_in_schema=False)
def staff_page(request: Request, session: Database):
    return render(request, session, "staff", duplicate=request.query_params.get("duplicate") == "1")

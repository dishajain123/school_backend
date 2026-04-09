import uuid
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_roles
from app.db.session import get_db
from app.schemas.timetable import TimetableUploadResponse, TimetableResponse
from app.services.timetable import TimetableService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/timetable", tags=["Timetable"])


@router.post("", response_model=TimetableUploadResponse, status_code=201)
async def upload_timetable(
    standard_id: uuid.UUID = Form(...),
    academic_year_id: Optional[uuid.UUID] = Form(None),
    section: Optional[str] = Form(None, description="Section (e.g. A, B). Leave blank for all sections."),
    file: UploadFile = File(..., description="Timetable file (PDF or image)"),
    current_user: CurrentUser = Depends(
        require_roles(RoleEnum.PRINCIPAL, RoleEnum.TEACHER)
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    PRINCIPAL and TEACHER.
    Uploads a timetable file and upserts the record for the class/section.
    """
    return await TimetableService(db).upload_timetable(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
        file=file,
        section=section,
    )


@router.get("/sections", response_model=list[str])
async def list_timetable_sections_compat(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(
        require_roles(RoleEnum.PRINCIPAL, RoleEnum.TEACHER)
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Compatibility route for clients sending:
    /timetable/sections?standard_id=<uuid>&academic_year_id=<uuid>
    Canonical route remains /timetable/{standard_id}/sections.
    """
    return await TimetableService(db).list_sections(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
    )


@router.get("/{standard_id}", response_model=TimetableResponse)
async def get_timetable(
    standard_id: uuid.UUID,
    academic_year_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None, description="Section filter"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the timetable presigned URL for the class.
    Students/Parents are scoped to their own class.
    """
    return await TimetableService(db).get_timetable(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
        section=section,
    )


@router.get(
    "/{standard_id}/sections",
    response_model=list[str],
)
async def list_timetable_sections(
    standard_id: uuid.UUID,
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(
        require_roles(RoleEnum.PRINCIPAL, RoleEnum.TEACHER)
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns section options where timetable records exist for the selected class.
    """
    return await TimetableService(db).list_sections(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
    )

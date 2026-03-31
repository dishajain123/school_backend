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
    file: UploadFile = File(..., description="Timetable file (PDF or image)"),
    current_user: CurrentUser = Depends(require_roles(RoleEnum.PRINCIPAL)),
    db: AsyncSession = Depends(get_db),
):
    """
    PRINCIPAL only.
    Uploads a timetable file and upserts the record for the class.
    """
    return await TimetableService(db).upload_timetable(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
        file=file,
    )


@router.get("/{standard_id}", response_model=TimetableResponse)
async def get_timetable(
    standard_id: uuid.UUID,
    academic_year_id: Optional[uuid.UUID] = Query(None),
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
    )

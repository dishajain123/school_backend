import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import CurrentUser, get_current_user

router = APIRouter(prefix="/teacher-class-subjects", tags=["Teacher Assignments"])

_DEPRECATION_DETAIL = "Deprecated. Use /teacher-assignments"


def _gone() -> None:
    raise HTTPException(status_code=410, detail=_DEPRECATION_DETAIL)


@router.get("/mine", deprecated=True)
async def list_my_assignments_deprecated(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    _gone()


@router.get("", deprecated=True)
async def list_assignments_deprecated(
    teacher_id: Optional[uuid.UUID] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    _gone()

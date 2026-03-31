import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.schemas.assignment import AssignmentCreate, AssignmentUpdate, AssignmentResponse, AssignmentListResponse
from app.services.assignment import AssignmentService

router = APIRouter(prefix="/assignments", tags=["Assignments"])


@router.post("", response_model=AssignmentResponse, status_code=201)
async def create_assignment(
    background_tasks: BackgroundTasks,
    title: str = Form(..., description="Assignment title"),
    standard_id: uuid.UUID = Form(...),
    subject_id: uuid.UUID = Form(...),
    due_date: date = Form(...),
    academic_year_id: uuid.UUID = Form(...),
    description: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None, description="Optional assignment file (PDF, image, etc.)"),
    current_user: CurrentUser = Depends(require_permission("assignment:create")),
    db: AsyncSession = Depends(get_db),
):
    body = AssignmentCreate(
        title=title,
        description=description,
        standard_id=standard_id,
        subject_id=subject_id,
        due_date=due_date,
        academic_year_id=academic_year_id,
    )
    return await AssignmentService(db).create(body, current_user, background_tasks, file)


@router.get("", response_model=AssignmentListResponse)
async def list_assignments(
    standard_id: Optional[uuid.UUID] = Query(None, description="Filter by class/standard"),
    subject_id: Optional[uuid.UUID] = Query(None, description="Filter by subject"),
    academic_year_id: Optional[uuid.UUID] = Query(None, description="Filter by academic year"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_permission("assignment:read")),
    db: AsyncSession = Depends(get_db),
):
    return await AssignmentService(db).list_assignments(
        current_user=current_user,
        standard_id=standard_id,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )


@router.get("/{assignment_id}", response_model=AssignmentResponse)
async def get_assignment(
    assignment_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("assignment:read")),
    db: AsyncSession = Depends(get_db),
):
    return await AssignmentService(db).get_assignment(assignment_id, current_user)


@router.patch("/{assignment_id}", response_model=AssignmentResponse)
async def update_assignment(
    assignment_id: uuid.UUID,
    body: AssignmentUpdate,
    current_user: CurrentUser = Depends(require_permission("assignment:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    TEACHER only. Updates title, description, due_date, or active status.
    The requesting teacher must be the original creator of the assignment.
    """
    return await AssignmentService(db).update_assignment(assignment_id, body, current_user)
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.schemas.submission import SubmissionGrade, SubmissionResponse, SubmissionListResponse
from app.services.submission import SubmissionService

router = APIRouter(prefix="/submissions", tags=["Submissions"])


@router.post("", response_model=SubmissionResponse, status_code=201)
async def create_submission(
    background_tasks: BackgroundTasks,
    assignment_id: uuid.UUID = Form(...),
    student_id: uuid.UUID = Form(..., description="The student whose work this is"),
    text_response: Optional[str] = Form(None, description="Text answer (optional if file provided)"),
    file: Optional[UploadFile] = File(None, description="Submitted file (optional if text provided)"),
    current_user: CurrentUser = Depends(require_permission("submission:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    STUDENT or PARENT (`submission:create`).

    - `student_id` is ALWAYS the student whose work it is.
    - `performed_by` is automatically set to `current_user.id` (student or parent user).
    - If PARENT: service verifies `students.parent_id == current_user.parent_id`.
    - If STUDENT: service verifies `students.user_id == current_user.id`.
    - Late flag is set automatically if `submitted_at.date() > assignment.due_date`.
    """
    from app.schemas.submission import SubmissionCreate

    body = SubmissionCreate(
        assignment_id=assignment_id,
        student_id=student_id,
        text_response=text_response,
    )
    return await SubmissionService(db).create_submission(
        body, current_user, background_tasks, file
    )


@router.get("", response_model=SubmissionListResponse)
async def list_submissions(
    assignment_id: uuid.UUID = Query(..., description="Filter submissions by assignment"),
    standard_id: Optional[uuid.UUID] = Query(None, description="Optional class/standard filter"),
    subject_id: Optional[uuid.UUID] = Query(None, description="Optional subject filter"),
    section: Optional[str] = Query(None, description="Optional section filter"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_permission("assignment:read")),
    db: AsyncSession = Depends(get_db),
):
    """
    - TEACHER / PRINCIPAL / TRUSTEE: see ALL submissions for the assignment.
    - STUDENT: sees only their own submission.
    - PARENT: sees submissions for all their children in the assignment's standard.
    """
    return await SubmissionService(db).list_submissions(
        assignment_id=assignment_id,
        standard_id=standard_id,
        subject_id=subject_id,
        section=section,
        current_user=current_user,
        page=page,
        page_size=page_size,
    )


@router.patch("/{submission_id}/grade", response_model=SubmissionResponse)
async def grade_submission(
    submission_id: uuid.UUID,
    body: SubmissionGrade,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("submission:grade")),
    db: AsyncSession = Depends(get_db),
):
    """
    TEACHER only (`submission:grade`).
    Teacher must be the creator of the assignment this submission belongs to.
    On success, a notification is sent to the student and their parent.
    """
    return await SubmissionService(db).grade_submission(
        submission_id, body, current_user, background_tasks
    )


@router.patch("/{submission_id}/review", response_model=SubmissionResponse)
async def review_submission(
    submission_id: uuid.UUID,
    body: SubmissionGrade,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("submission:grade")),
    db: AsyncSession = Depends(get_db),
):
    """
    Teacher review endpoint with flexible actions:
    - set grade (optional)
    - add feedback (optional)
    - approve/unapprove (optional)
    At least one action is required.
    """
    return await SubmissionService(db).grade_submission(
        submission_id, body, current_user, background_tasks
    )

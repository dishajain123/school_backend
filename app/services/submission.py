import uuid
import math
from datetime import datetime, timezone
from typing import Optional
from fastapi import UploadFile, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.repositories.submission import SubmissionRepository
from app.repositories.assignment import AssignmentRepository
from app.repositories.notification import NotificationRepository
from app.schemas.submission import (
    SubmissionCreate,
    SubmissionGrade,
    SubmissionResponse,
    SubmissionListResponse,
)
from app.core.dependencies import CurrentUser
from app.core.exceptions import NotFoundException, ForbiddenException
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority
from app.integrations.minio_client import minio_client

SUBMISSION_BUCKET = "submissions"


async def _assert_parent_owns_student(
    db: AsyncSession,
    student_id: uuid.UUID,
    current_user: CurrentUser,
) -> None:
    from app.models.student import Student

    result = await db.execute(
        select(Student).where(
            and_(
                Student.id == student_id,
                Student.school_id == current_user.school_id,
            )
        )
    )
    student = result.scalar_one_or_none()
    if not student:
        raise NotFoundException("Student not found")
    if student.parent_id != current_user.parent_id:
        raise ForbiddenException("Not your child")


async def _notify_submission_graded(
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    submission_id: uuid.UUID,
    assignment_title: str,
    grade: str,
) -> None:
    """Opens its own DB session — never reuses the request session."""
    from app.db.session import AsyncSessionLocal
    from app.models.student import Student
    from app.models.parent import Parent

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Student.user_id, Student.parent_id).where(
                and_(
                    Student.id == student_id,
                    Student.school_id == school_id,
                )
            )
        )
        row = result.one_or_none()
        if not row:
            return

        student_user_id, parent_id = row
        user_ids_to_notify: set[uuid.UUID] = set()

        if student_user_id:
            user_ids_to_notify.add(student_user_id)

        if parent_id:
            parent_result = await db.execute(
                select(Parent.user_id).where(Parent.id == parent_id)
            )
            parent_user_id = parent_result.scalar_one_or_none()
            if parent_user_id:
                user_ids_to_notify.add(parent_user_id)

        notification_repo = NotificationRepository(db)
        for user_id in user_ids_to_notify:
            await notification_repo.create(
                {
                    "user_id": user_id,
                    "title": "Assignment Graded",
                    "body": (
                        f"Your submission for '{assignment_title}' "
                        f"has been graded. Grade: {grade}"
                    ),
                    "type": NotificationType.SUBMISSION,
                    "priority": NotificationPriority.MEDIUM,
                    "reference_id": submission_id,
                }
            )

        await db.commit()


class SubmissionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SubmissionRepository(db)
        self.assignment_repo = AssignmentRepository(db)

    def _build_response(self, submission) -> SubmissionResponse:
        data = SubmissionResponse.model_validate(submission)
        if submission.file_key:
            data.file_url = minio_client.generate_presigned_url(
                SUBMISSION_BUCKET, submission.file_key
            )
        return data

    async def create_submission(
        self,
        body: SubmissionCreate,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
        file: Optional[UploadFile] = None,
    ) -> SubmissionResponse:
        from app.models.student import Student

        if current_user.role == RoleEnum.PARENT:
            await _assert_parent_owns_student(self.db, body.student_id, current_user)

        elif current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == current_user.school_id,
                    )
                )
            )
            own_student_id = result.scalar_one_or_none()
            if not own_student_id or own_student_id != body.student_id:
                raise ForbiddenException("You can only submit for yourself")

        assignment = await self.assignment_repo.get_by_id(
            body.assignment_id, current_user.school_id
        )
        if not assignment:
            raise NotFoundException("Assignment not found")
        if not assignment.is_active:
            raise ForbiddenException("This assignment is no longer accepting submissions")

        existing = await self.repo.get_existing(body.assignment_id, body.student_id)
        if existing:
            raise HTTPException(
                status_code=409,
                detail="A submission already exists for this student on this assignment",
            )

        if not file and not body.text_response:
            raise HTTPException(
                status_code=422,
                detail="At least one of file or text_response must be provided",
            )

        file_key: Optional[str] = None
        if file and file.filename:
            content = await file.read()
            file_key = (
                f"{current_user.school_id}/{body.assignment_id}"
                f"/{body.student_id}/{uuid.uuid4()}_{file.filename}"
            )
            minio_client.upload_file(
                bucket=SUBMISSION_BUCKET,
                key=file_key,
                file_bytes=content,
                content_type=file.content_type or "application/octet-stream",
            )

        is_late = datetime.now(tz=timezone.utc).date() > assignment.due_date

        submission = await self.repo.create(
            {
                "assignment_id": body.assignment_id,
                "student_id": body.student_id,
                "performed_by": current_user.id,
                "file_key": file_key,
                "text_response": body.text_response,
                "is_late": is_late,
                "school_id": current_user.school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(submission)
        return self._build_response(submission)

    async def grade_submission(
        self,
        submission_id: uuid.UUID,
        body: SubmissionGrade,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> SubmissionResponse:
        from app.services.assignment import _get_teacher_id

        submission = await self.repo.get_by_id(submission_id, current_user.school_id)
        if not submission:
            raise NotFoundException("Submission not found")

        assignment = await self.assignment_repo.get_by_id(
            submission.assignment_id, current_user.school_id
        )
        if not assignment:
            raise NotFoundException("Assignment not found")

        teacher_id = await _get_teacher_id(
            self.db, current_user.id, current_user.school_id
        )
        if assignment.teacher_id != teacher_id:
            raise ForbiddenException(
                "You can only grade submissions for your own assignments"
            )

        updated = await self.repo.update(
            submission,
            {
                "grade": body.grade,
                "feedback": body.feedback,
                "is_graded": True,
            },
        )
        await self.db.commit()
        await self.db.refresh(updated)

        background_tasks.add_task(
            _notify_submission_graded,
            submission.student_id,
            current_user.school_id,
            submission_id,
            assignment.title,
            body.grade,
        )

        return self._build_response(updated)

    async def list_submissions(
        self,
        assignment_id: uuid.UUID,
        current_user: CurrentUser,
        page: int,
        page_size: int,
    ) -> SubmissionListResponse:
        from app.models.student import Student

        assignment = await self.assignment_repo.get_by_id(
            assignment_id, current_user.school_id
        )
        if not assignment:
            raise NotFoundException("Assignment not found")

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == current_user.school_id,
                    )
                )
            )
            own_student_id = result.scalar_one_or_none()
            items, total = await self.repo.list_by_assignment(
                assignment_id=assignment_id,
                school_id=current_user.school_id,
                student_id=own_student_id,
                page=page,
                page_size=page_size,
            )
            return SubmissionListResponse(
                items=[self._build_response(s) for s in items],
                total=total,
                page=page,
                page_size=page_size,
                total_pages=math.ceil(total / page_size) if total else 0,
            )

        if current_user.role == RoleEnum.PARENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == current_user.school_id,
                        Student.standard_id == assignment.standard_id,
                    )
                )
            )
            child_ids = [row[0] for row in result.all()]
            items = await self.repo.list_by_assignment_for_students(
                assignment_id=assignment_id,
                school_id=current_user.school_id,
                student_ids=child_ids,
            )
            return SubmissionListResponse(
                items=[self._build_response(s) for s in items],
                total=len(items),
                page=1,
                page_size=len(items) or page_size,
                total_pages=1 if items else 0,
            )

        items, total = await self.repo.list_by_assignment(
            assignment_id=assignment_id,
            school_id=current_user.school_id,
            page=page,
            page_size=page_size,
        )
        return SubmissionListResponse(
            items=[self._build_response(s) for s in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )
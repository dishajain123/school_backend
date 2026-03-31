import uuid
import math
from datetime import datetime, timezone
from typing import Optional
from fastapi import UploadFile, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.repositories.assignment import AssignmentRepository
from app.repositories.teacher_class_subject import TeacherClassSubjectRepository
from app.repositories.notification import NotificationRepository
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentUpdate,
    AssignmentResponse,
    AssignmentListResponse,
)
from app.core.dependencies import CurrentUser
from app.core.exceptions import NotFoundException, ForbiddenException
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority
from app.integrations.minio_client import minio_client

ASSIGNMENT_BUCKET = "assignments"


# ── Shared helpers (also imported by submission service) ──────────────────────

async def _get_teacher_id(
    db: AsyncSession,
    user_id: uuid.UUID,
    school_id: uuid.UUID,
) -> uuid.UUID:
    from app.models.teacher import Teacher

    result = await db.execute(
        select(Teacher.id).where(
            and_(
                Teacher.user_id == user_id,
                Teacher.school_id == school_id,
            )
        )
    )
    teacher_id = result.scalar_one_or_none()
    if not teacher_id:
        raise ForbiddenException("Teacher profile not found for this user")
    return teacher_id


async def _assert_teacher_owns_class_subject(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    standard_id: uuid.UUID,
    subject_id: uuid.UUID,
    academic_year_id: uuid.UUID,
) -> None:
    repo = TeacherClassSubjectRepository(db)
    record = await repo.find_assignment(
        teacher_id=teacher_id,
        standard_id=standard_id,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
    )
    if not record:
        raise ForbiddenException(
            "You are not assigned to teach this subject in this class"
        )


# ── Background task ───────────────────────────────────────────────────────────

async def _notify_assignment_created(
    db: AsyncSession,
    school_id: uuid.UUID,
    standard_id: uuid.UUID,
    assignment_id: uuid.UUID,
    assignment_title: str,
) -> None:
    """
    Runs as a BackgroundTask after assignment creation.
    Notifies all students in the standard and their parents.
    """
    from app.models.student import Student
    from app.models.parent import Parent

    # Collect student user_ids and parent_ids in the standard
    result = await db.execute(
        select(Student.user_id, Student.parent_id).where(
            and_(
                Student.standard_id == standard_id,
                Student.school_id == school_id,
            )
        )
    )
    rows = result.all()

    user_ids_to_notify: set[uuid.UUID] = set()
    parent_ids: set[uuid.UUID] = set()

    for student_user_id, parent_id in rows:
        if student_user_id:
            user_ids_to_notify.add(student_user_id)
        if parent_id:
            parent_ids.add(parent_id)

    # Resolve parent user_ids (parent login is always mandatory)
    if parent_ids:
        parent_result = await db.execute(
            select(Parent.user_id).where(Parent.id.in_(list(parent_ids)))
        )
        for (parent_user_id,) in parent_result:
            if parent_user_id:
                user_ids_to_notify.add(parent_user_id)

    notification_repo = NotificationRepository(db)
    for user_id in user_ids_to_notify:
        await notification_repo.create(
            {
                "user_id": user_id,
                "title": "New Assignment Posted",
                "body": f"A new assignment '{assignment_title}' has been posted for your class.",
                "type": NotificationType.ASSIGNMENT,
                "priority": NotificationPriority.MEDIUM,
                "reference_id": assignment_id,
            }
        )

    await db.commit()


# ── Service ───────────────────────────────────────────────────────────────────

class AssignmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AssignmentRepository(db)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_response(self, assignment) -> AssignmentResponse:
        data = AssignmentResponse.model_validate(assignment)
        if assignment.file_key:
            data.file_url = minio_client.generate_presigned_url(
                ASSIGNMENT_BUCKET, assignment.file_key
            )
        return data

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(
        self,
        body: AssignmentCreate,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
        file: Optional[UploadFile] = None,
    ) -> AssignmentResponse:
        teacher_id = await _get_teacher_id(
            self.db, current_user.id, current_user.school_id
        )
        await _assert_teacher_owns_class_subject(
            self.db,
            teacher_id=teacher_id,
            standard_id=body.standard_id,
            subject_id=body.subject_id,
            academic_year_id=body.academic_year_id,
        )

        file_key: Optional[str] = None
        if file and file.filename:
            content = await file.read()
            file_key = (
                f"{current_user.school_id}/{body.standard_id}"
                f"/{uuid.uuid4()}_{file.filename}"
            )
            minio_client.upload_file(
                bucket=ASSIGNMENT_BUCKET,
                key=file_key,
                file_bytes=content,
                content_type=file.content_type or "application/octet-stream",
            )

        assignment = await self.repo.create(
            {
                "title": body.title,
                "description": body.description,
                "teacher_id": teacher_id,
                "standard_id": body.standard_id,
                "subject_id": body.subject_id,
                "due_date": body.due_date,
                "file_key": file_key,
                "academic_year_id": body.academic_year_id,
                "school_id": current_user.school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(assignment)

        background_tasks.add_task(
            _notify_assignment_created,
            self.db,
            current_user.school_id,
            body.standard_id,
            assignment.id,
            assignment.title,
        )

        return self._build_response(assignment)

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_assignments(
        self,
        current_user: CurrentUser,
        standard_id: Optional[uuid.UUID],
        subject_id: Optional[uuid.UUID],
        academic_year_id: Optional[uuid.UUID],
        is_active: Optional[bool],
        page: int,
        page_size: int,
    ) -> AssignmentListResponse:
        from app.models.student import Student

        teacher_id_filter: Optional[uuid.UUID] = None
        resolved_standard_id: Optional[uuid.UUID] = standard_id

        if current_user.role == RoleEnum.TEACHER:
            # Scope to this teacher's own assignments only
            teacher_id_filter = await _get_teacher_id(
                self.db, current_user.id, current_user.school_id
            )

        elif current_user.role == RoleEnum.STUDENT:
            # Resolve student's own standard; reject mismatched filter
            result = await self.db.execute(
                select(Student.standard_id).where(
                    Student.user_id == current_user.id
                )
            )
            own_standard_id = result.scalar_one_or_none()
            if standard_id and own_standard_id and standard_id != own_standard_id:
                raise ForbiddenException("You can only view assignments for your own class")
            resolved_standard_id = own_standard_id or standard_id

        elif current_user.role == RoleEnum.PARENT:
            # Verify the requested standard has a child belonging to this parent
            if standard_id:
                result = await self.db.execute(
                    select(Student.id).where(
                        and_(
                            Student.standard_id == standard_id,
                            Student.parent_id == current_user.parent_id,
                            Student.school_id == current_user.school_id,
                        )
                    )
                )
                if not result.scalar_one_or_none():
                    raise ForbiddenException("You do not have a child in this class")

        items, total = await self.repo.list_by_school(
            school_id=current_user.school_id,
            standard_id=resolved_standard_id,
            subject_id=subject_id,
            academic_year_id=academic_year_id,
            teacher_id=teacher_id_filter,
            is_active=is_active,
            page=page,
            page_size=page_size,
        )

        return AssignmentListResponse(
            items=[self._build_response(a) for a in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    # ── Get single ────────────────────────────────────────────────────────────

    async def get_assignment(
        self,
        assignment_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> AssignmentResponse:
        from app.models.student import Student

        assignment = await self.repo.get_by_id(assignment_id, current_user.school_id)
        if not assignment:
            raise NotFoundException("Assignment not found")

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.standard_id == assignment.standard_id,
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise ForbiddenException("This assignment is not for your class")

        elif current_user.role == RoleEnum.PARENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.standard_id == assignment.standard_id,
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == current_user.school_id,
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise ForbiddenException("You do not have a child in this class")

        return self._build_response(assignment)

    # ── Update ────────────────────────────────────────────────────────────────

    async def update_assignment(
        self,
        assignment_id: uuid.UUID,
        body: AssignmentUpdate,
        current_user: CurrentUser,
    ) -> AssignmentResponse:
        assignment = await self.repo.get_by_id(assignment_id, current_user.school_id)
        if not assignment:
            raise NotFoundException("Assignment not found")

        # Only the teacher who created it may update it
        teacher_id = await _get_teacher_id(
            self.db, current_user.id, current_user.school_id
        )
        if assignment.teacher_id != teacher_id:
            raise ForbiddenException("You can only update your own assignments")

        update_data = body.model_dump(exclude_none=True)
        updated = await self.repo.update(assignment, update_data)
        await self.db.commit()
        await self.db.refresh(updated)
        return self._build_response(updated)
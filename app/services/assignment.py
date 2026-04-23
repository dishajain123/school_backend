import uuid
import math
from typing import Optional
from fastapi import UploadFile, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.repositories.assignment import AssignmentRepository
from app.repositories.notification import NotificationRepository
from app.repositories.teacher_class_subject import TeacherClassSubjectRepository
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentUpdate,
    AssignmentResponse,
    AssignmentListResponse,
)
from app.core.dependencies import CurrentUser
from app.core.exceptions import NotFoundException, ForbiddenException
from app.core.logging import get_logger
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority
from app.utils.date_utils import today_in_app_timezone
from app.integrations.minio_client import minio_client

ASSIGNMENT_BUCKET = "assignments"
logger = get_logger(__name__)


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
    school_id: uuid.UUID,
    standard_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    assignment_id: uuid.UUID,
    assignment_title: str,
) -> None:
    """
    Runs as a BackgroundTask after assignment creation.
    Opens its own DB session — never reuses the request session.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.student import Student
    from app.models.parent import Parent

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Student.user_id, Student.parent_id).where(
                and_(
                    Student.standard_id == standard_id,
                    Student.academic_year_id == academic_year_id,
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
                "is_active": True,
                "academic_year_id": body.academic_year_id,
                "school_id": current_user.school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(assignment)

        logger.info(
            "ASSIGNMENT_CREATE school_id=%s user_id=%s role=%s teacher_id=%s assignment_id=%s standard_id=%s subject_id=%s academic_year_id=%s due_date=%s is_active=%s",
            str(current_user.school_id),
            str(current_user.id),
            str(current_user.role),
            str(teacher_id),
            str(assignment.id),
            str(body.standard_id),
            str(body.subject_id),
            str(body.academic_year_id),
            str(body.due_date),
            str(assignment.is_active),
        )

        background_tasks.add_task(
            _notify_assignment_created,
            current_user.school_id,
            body.standard_id,
            body.academic_year_id,
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
        is_overdue: Optional[bool],
        is_submitted: Optional[bool],
        page: int,
        page_size: int,
    ) -> AssignmentListResponse:
        from app.models.student import Student

        teacher_id_filter: Optional[uuid.UUID] = None
        resolved_standard_id: Optional[uuid.UUID] = standard_id
        submission_student_ids: Optional[list[uuid.UUID]] = None

        if current_user.role == RoleEnum.TEACHER:
            # Strict ownership: teacher sees only assignments they created.
            teacher_id_filter = await _get_teacher_id(
                self.db, current_user.id, current_user.school_id
            )

        elif current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id, Student.standard_id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == current_user.school_id,
                    )
                )
            )
            own_row = result.one_or_none()
            own_student_id = own_row[0] if own_row else None
            own_standard_id = own_row[1] if own_row else None
            if standard_id and own_standard_id and standard_id != own_standard_id:
                raise ForbiddenException("You can only view assignments for your own class")
            resolved_standard_id = own_standard_id or standard_id
            if own_student_id:
                submission_student_ids = [own_student_id]

        elif current_user.role == RoleEnum.PARENT:
            child_query = [
                Student.parent_id == current_user.parent_id,
                Student.school_id == current_user.school_id,
            ]
            if standard_id:
                child_query.append(Student.standard_id == standard_id)
            child_result = await self.db.execute(
                select(Student.id).where(and_(*child_query))
            )
            child_ids = [row[0] for row in child_result.all()]
            if standard_id:
                if not child_ids:
                    raise ForbiddenException("You do not have a child in this class")
            submission_student_ids = child_ids

        items, total = await self.repo.list_by_school(
            school_id=current_user.school_id,
            standard_id=resolved_standard_id,
            subject_id=subject_id,
            academic_year_id=academic_year_id,
            teacher_id=teacher_id_filter,
            is_active=is_active,
            is_overdue=is_overdue,
            is_submitted=is_submitted,
            submission_student_ids=submission_student_ids,
            reference_date=today_in_app_timezone(),
            page=page,
            page_size=page_size,
        )

        logger.info(
            "ASSIGNMENT_LIST school_id=%s user_id=%s role=%s teacher_id_filter=%s standard_id=%s subject_id=%s academic_year_id=%s is_active=%s is_overdue=%s is_submitted=%s reference_date=%s page=%s page_size=%s returned=%s total=%s",
            str(current_user.school_id),
            str(current_user.id),
            str(current_user.role),
            str(teacher_id_filter) if teacher_id_filter else "None",
            str(resolved_standard_id) if resolved_standard_id else "None",
            str(subject_id) if subject_id else "None",
            str(academic_year_id) if academic_year_id else "None",
            str(is_active) if is_active is not None else "None",
            str(is_overdue) if is_overdue is not None else "None",
            str(is_submitted) if is_submitted is not None else "None",
            str(today_in_app_timezone()),
            str(page),
            str(page_size),
            str(len(items)),
            str(total),
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
                        Student.school_id == current_user.school_id,
                        Student.standard_id == assignment.standard_id,
                        Student.academic_year_id == assignment.academic_year_id,
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
                        Student.academic_year_id == assignment.academic_year_id,
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

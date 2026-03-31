import uuid
import math
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ConflictException, ValidationException
from app.repositories.homework import HomeworkRepository
from app.repositories.notification import NotificationRepository
from app.schemas.homework import HomeworkCreate, HomeworkResponse, HomeworkListResponse
from app.services.academic_year import get_active_year
from app.services.assignment import _get_teacher_id, _assert_teacher_owns_class_subject
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority


async def _notify_homework_created(
    school_id: uuid.UUID,
    standard_id: uuid.UUID,
    homework_id: uuid.UUID,
    record_date: date,
) -> None:
    """Opens its own DB session — never reuses the request session."""
    from app.db.session import AsyncSessionLocal
    from app.models.student import Student
    from app.models.parent import Parent

    async with AsyncSessionLocal() as db:
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
                    "title": "New Homework Posted",
                    "body": f"New homework has been posted for {record_date.isoformat()}",
                    "type": NotificationType.HOMEWORK,
                    "priority": NotificationPriority.LOW,
                    "reference_id": homework_id,
                }
            )

        await db.commit()


class HomeworkService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = HomeworkRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def create_homework(
        self,
        body: HomeworkCreate,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> HomeworkResponse:
        school_id = self._ensure_school(current_user)

        record_date = body.date or datetime.now(timezone.utc).date()
        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
        await _assert_teacher_owns_class_subject(
            self.db,
            teacher_id=teacher_id,
            standard_id=body.standard_id,
            subject_id=body.subject_id,
            academic_year_id=academic_year_id,
        )

        existing = await self.repo.get_duplicate(
            school_id=school_id,
            standard_id=body.standard_id,
            subject_id=body.subject_id,
            record_date=record_date,
            academic_year_id=academic_year_id,
        )
        if existing:
            raise ConflictException("Homework already exists for this class and date")

        homework = await self.repo.create(
            {
                "description": body.description,
                "date": record_date,
                "teacher_id": teacher_id,
                "standard_id": body.standard_id,
                "subject_id": body.subject_id,
                "academic_year_id": academic_year_id,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(homework)

        background_tasks.add_task(
            _notify_homework_created,
            school_id,
            body.standard_id,
            homework.id,
            record_date,
        )

        return HomeworkResponse.model_validate(homework)

    async def list_homework(
        self,
        current_user: CurrentUser,
        record_date: Optional[date],
        standard_id: Optional[uuid.UUID],
        subject_id: Optional[uuid.UUID],
        academic_year_id: Optional[uuid.UUID],
        page: int,
        page_size: int,
    ) -> HomeworkListResponse:
        school_id = self._ensure_school(current_user)

        resolved_date = record_date or datetime.now(timezone.utc).date()
        resolved_year_id = academic_year_id
        if not resolved_year_id:
            resolved_year_id = (await get_active_year(school_id, self.db)).id

        teacher_id_filter: Optional[uuid.UUID] = None
        standard_ids_filter: Optional[list[uuid.UUID]] = None
        resolved_standard_id: Optional[uuid.UUID] = standard_id

        from app.models.student import Student

        if current_user.role == RoleEnum.TEACHER:
            teacher_id_filter = await _get_teacher_id(
                self.db, current_user.id, school_id
            )

        elif current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.standard_id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_standard_id = result.scalar_one_or_none()
            if not own_standard_id:
                raise ForbiddenException("Student profile not found or class not assigned")
            if standard_id and standard_id != own_standard_id:
                raise ForbiddenException("You can only view homework for your own class")
            standard_ids_filter = [own_standard_id]
            resolved_standard_id = None

        elif current_user.role == RoleEnum.PARENT:
            if standard_id:
                result = await self.db.execute(
                    select(Student.id).where(
                        and_(
                            Student.standard_id == standard_id,
                            Student.parent_id == current_user.parent_id,
                            Student.school_id == school_id,
                        )
                    )
                )
                if not result.scalar_one_or_none():
                    raise ForbiddenException("You do not have a child in this class")
                standard_ids_filter = [standard_id]
                resolved_standard_id = None
            else:
                result = await self.db.execute(
                    select(Student.standard_id).where(
                        and_(
                            Student.parent_id == current_user.parent_id,
                            Student.school_id == school_id,
                        )
                    )
                )
                standard_ids = [row[0] for row in result.all() if row[0] is not None]
                standard_ids_filter = list(dict.fromkeys(standard_ids))
                resolved_standard_id = None

        items, total = await self.repo.list_by_school(
            school_id=school_id,
            standard_id=resolved_standard_id,
            standard_ids=standard_ids_filter,
            subject_id=subject_id,
            record_date=resolved_date,
            academic_year_id=resolved_year_id,
            teacher_id=teacher_id_filter,
            page=page,
            page_size=page_size,
        )

        return HomeworkListResponse(
            items=[HomeworkResponse.model_validate(h) for h in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )
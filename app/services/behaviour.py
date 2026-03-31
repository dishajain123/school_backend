import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException
from app.repositories.behaviour import BehaviourRepository
from app.repositories.notification import NotificationRepository
from app.services.academic_year import get_active_year
from app.services.assignment import _get_teacher_id
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority, IncidentType
from app.schemas.behaviour import BehaviourCreate, BehaviourListResponse, BehaviourResponse


async def _assert_teacher_owns_student_class(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    school_id: uuid.UUID,
) -> None:
    from app.models.student import Student
    from app.models.teacher_class_subject import TeacherClassSubject

    result = await db.execute(
        select(Student.standard_id, Student.section).where(
            and_(
                Student.id == student_id,
                Student.school_id == school_id,
            )
        )
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundException("Student")

    standard_id, section = row
    if not standard_id or not section:
        raise ValidationException("Student class or section not set")

    result = await db.execute(
        select(TeacherClassSubject.id).where(
            and_(
                TeacherClassSubject.teacher_id == teacher_id,
                TeacherClassSubject.standard_id == standard_id,
                TeacherClassSubject.section == section,
                TeacherClassSubject.academic_year_id == academic_year_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        raise ForbiddenException("You are not assigned to this student's class")


async def _notify_parent(
    db: AsyncSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    log_id: uuid.UUID,
) -> None:
    from app.models.student import Student
    from app.models.parent import Parent

    result = await db.execute(
        select(Student.parent_id).where(
            and_(
                Student.id == student_id,
                Student.school_id == school_id,
            )
        )
    )
    parent_id = result.scalar_one_or_none()
    if not parent_id:
        return

    parent_result = await db.execute(
        select(Parent.user_id).where(Parent.id == parent_id)
    )
    parent_user_id = parent_result.scalar_one_or_none()
    if not parent_user_id:
        return

    repo = NotificationRepository(db)
    await repo.create(
        {
            "user_id": parent_user_id,
            "title": "Behaviour Update",
            "body": "A new behaviour log was recorded for your child.",
            "type": NotificationType.BEHAVIOUR,
            "priority": NotificationPriority.MEDIUM,
            "reference_id": log_id,
        }
    )
    await db.commit()


class BehaviourService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BehaviourRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def create_log(
        self,
        body: BehaviourCreate,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> BehaviourResponse:
        school_id = self._ensure_school(current_user)
        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
        await _assert_teacher_owns_student_class(
            self.db,
            teacher_id=teacher_id,
            student_id=body.student_id,
            academic_year_id=academic_year_id,
            school_id=school_id,
        )

        incident_date = body.incident_date or datetime.now(timezone.utc).date()

        log = await self.repo.create(
            {
                "student_id": body.student_id,
                "teacher_id": teacher_id,
                "incident_type": body.incident_type,
                "description": body.description,
                "severity": body.severity,
                "incident_date": incident_date,
                "academic_year_id": academic_year_id,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(log)

        if body.incident_type == IncidentType.NEGATIVE:
            background_tasks.add_task(
                _notify_parent,
                self.db,
                body.student_id,
                school_id,
                log.id,
            )

        return BehaviourResponse.model_validate(log)

    async def list_logs(
        self,
        student_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> BehaviourListResponse:
        school_id = self._ensure_school(current_user)

        from app.models.student import Student

        if current_user.role == RoleEnum.PARENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.id == student_id,
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == school_id,
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise ForbiddenException("Not your child")

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
            academic_year_id = (await get_active_year(school_id, self.db)).id
            await _assert_teacher_owns_student_class(
                self.db,
                teacher_id=teacher_id,
                student_id=student_id,
                academic_year_id=academic_year_id,
                school_id=school_id,
            )

        logs = await self.repo.list_by_student(school_id, student_id)
        return BehaviourListResponse(
            items=[BehaviourResponse.model_validate(l) for l in logs],
            total=len(logs),
        )

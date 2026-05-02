import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import select, and_, func
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

    normalized_section = func.upper(func.trim(section))
    result = await db.execute(
        select(TeacherClassSubject.id).where(
            and_(
                TeacherClassSubject.teacher_id == teacher_id,
                TeacherClassSubject.standard_id == standard_id,
                func.upper(func.trim(TeacherClassSubject.section)) == normalized_section,
                TeacherClassSubject.academic_year_id == academic_year_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        raise ForbiddenException("You are not assigned to this student's class")


# FIX: _notify_parent must open its own DB session.
# The previous version accepted `db: AsyncSession` as a parameter and was
# called via background_tasks.add_task(self.db, ...). By the time the
# background task runs the request session is already closed, causing
# DetachedInstanceError or silent notification failures.
async def _notify_parent(
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    log_id: uuid.UUID,
) -> None:
    """Opens its own DB session — never reuses the request session."""
    from app.db.session import AsyncSessionLocal
    from app.models.student import Student
    from app.models.parent import Parent

    async with AsyncSessionLocal() as db:
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
                "description": (body.description or "").strip(),
                "severity": body.severity,
                "incident_date": incident_date,
                "academic_year_id": academic_year_id,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(log)

        # FIX: pass only plain serialisable arguments — no db session.
        if body.incident_type == IncidentType.NEGATIVE:
            background_tasks.add_task(
                _notify_parent,
                body.student_id,
                school_id,
                log.id,
            )

        return await self._to_behaviour_response(log)

    async def _to_behaviour_response(self, log) -> BehaviourResponse:
        from app.models.student import Student
        from app.models.user import User

        student_row = await self.db.execute(
            select(Student, User)
            .join(User, User.id == Student.user_id, isouter=True)
            .where(Student.id == log.student_id)
        )
        row = student_row.one_or_none()
        student_name: Optional[str] = None
        if row:
            student, user = row
            student_name = student.student_name
            if not student_name and user is not None:
                student_name = user.full_name or user.phone
            if not student_name:
                student_name = student.admission_number

        data = BehaviourResponse.model_validate(log)
        return data.model_copy(update={"student_name": student_name})

    async def _to_behaviour_responses(self, logs: list) -> list[BehaviourResponse]:
        from app.models.student import Student
        from app.models.user import User

        if not logs:
            return []

        student_ids = list({log.student_id for log in logs})
        rows = (
            await self.db.execute(
                select(
                    Student.id,
                    Student.admission_number,
                    User.full_name,
                    User.phone,
                )
                .join(User, User.id == Student.user_id, isouter=True)
                .where(Student.id.in_(student_ids))
            )
        ).all()

        name_map: dict[uuid.UUID, str] = {}
        for row in rows:
            derived = None
            if row.full_name and row.full_name.strip():
                derived = row.full_name.strip()
            if not derived and row.phone:
                derived = row.phone
            if not derived:
                derived = row.admission_number or "Student"
            name_map[row.id] = derived

        items: list[BehaviourResponse] = []
        for log in logs:
            data = BehaviourResponse.model_validate(log)
            items.append(
                data.model_copy(
                    update={"student_name": name_map.get(log.student_id, "Student")}
                )
            )
        return items

    async def list_logs(
        self,
        student_id: Optional[uuid.UUID],
        incident_type: Optional[IncidentType],
        standard_id: Optional[uuid.UUID],
        section: Optional[str],
        current_user: CurrentUser,
    ) -> BehaviourListResponse:
        school_id = self._ensure_school(current_user)
        section = section.strip() if section and section.strip() else None

        from app.models.student import Student

        if current_user.role == RoleEnum.PARENT:
            if not student_id:
                raise ValidationException("student_id is required for parent users")
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

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_student_id = result.scalar_one_or_none()
            if not own_student_id:
                raise NotFoundException("Student")
            if student_id and student_id != own_student_id:
                raise ForbiddenException("You can only view your own behaviour logs")
            student_id = own_student_id

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
            academic_year_id = (await get_active_year(school_id, self.db)).id
            if student_id:
                await _assert_teacher_owns_student_class(
                    self.db,
                    teacher_id=teacher_id,
                    student_id=student_id,
                    academic_year_id=academic_year_id,
                    school_id=school_id,
                )
            logs = await self.repo.list_for_teacher_scope(
                school_id=school_id,
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
                student_id=student_id,
                incident_type=incident_type,
                standard_id=standard_id,
                section=section,
                own_logs_only=True,
            )
            return BehaviourListResponse(
                items=await self._to_behaviour_responses(logs),
                total=len(logs),
            )

        logs = await self.repo.list_by_school(
            school_id=school_id,
            student_id=student_id,
            incident_type=incident_type,
            standard_id=standard_id,
            section=section,
        )
        return BehaviourListResponse(
            items=await self._to_behaviour_responses(logs),
            total=len(logs),
        )

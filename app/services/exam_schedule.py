import uuid
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.repositories.exam_schedule import ExamScheduleRepository
from app.repositories.notification import NotificationRepository
from app.schemas.exam_schedule import (
    ExamEntryCreate,
    ExamEntryResponse,
    ExamScheduleTable,
    ExamSeriesCreate,
    ExamSeriesResponse,
)
from app.services.academic_year import get_active_year
from app.utils.enums import NotificationPriority, NotificationType, RoleEnum


async def _notify_exam_schedule_published(
    school_id: uuid.UUID,
    standard_id: uuid.UUID,
    series_id: uuid.UUID,
    series_name: str,
) -> None:
    """Opens its own DB session — never reuses the request session."""
    from app.db.session import AsyncSessionLocal
    from app.models.parent import Parent
    from app.models.student import Student

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
                    "title": "Exam Schedule Published",
                    "body": f"Exam schedule '{series_name}' has been published.",
                    "type": NotificationType.EXAM,
                    "priority": NotificationPriority.MEDIUM,
                    "reference_id": series_id,
                }
            )

        await db.commit()


class ExamScheduleService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ExamScheduleRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def _assert_teacher_assigned_standard(
        self,
        *,
        school_id: uuid.UUID,
        current_user: CurrentUser,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> None:
        from app.models.teacher import Teacher
        from app.models.teacher_class_subject import TeacherClassSubject

        teacher_row = await self.db.execute(
            select(Teacher.id).where(
                and_(
                    Teacher.user_id == current_user.id,
                    Teacher.school_id == school_id,
                )
            )
        )
        teacher_id = teacher_row.scalar_one_or_none()
        if not teacher_id:
            raise ForbiddenException("Teacher profile not found")

        assignment = await self.db.execute(
            select(TeacherClassSubject.id).where(
                and_(
                    TeacherClassSubject.teacher_id == teacher_id,
                    TeacherClassSubject.standard_id == standard_id,
                    TeacherClassSubject.academic_year_id == academic_year_id,
                )
            )
        )
        if not assignment.scalar_one_or_none():
            raise ForbiddenException(
                "You can manage exam schedules only for your assigned class"
            )

    async def create_series(
        self,
        body: ExamSeriesCreate,
        current_user: CurrentUser,
    ) -> ExamSeriesResponse:
        school_id = self._ensure_school(current_user)
        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        if current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_assigned_standard(
                school_id=school_id,
                current_user=current_user,
                standard_id=body.standard_id,
                academic_year_id=academic_year_id,
            )

        existing = await self.repo.get_series_duplicate(
            school_id=school_id,
            standard_id=body.standard_id,
            academic_year_id=academic_year_id,
            name=body.name,
        )
        if existing:
            raise ConflictException("Exam series already exists for this class and year")

        series = await self.repo.create_series(
            {
                "name": body.name,
                "standard_id": body.standard_id,
                "academic_year_id": academic_year_id,
                "is_published": False,
                "created_by": current_user.id,
                "school_id": school_id,
            }
        )
        await self.db.refresh(series)
        return ExamSeriesResponse.model_validate(series)

    async def add_entry(
        self,
        series_id: uuid.UUID,
        body: ExamEntryCreate,
        current_user: CurrentUser,
    ) -> ExamEntryResponse:
        school_id = self._ensure_school(current_user)

        series = await self.repo.get_series_by_id(series_id, school_id)
        if not series:
            raise NotFoundException("Exam series")

        if current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_assigned_standard(
                school_id=school_id,
                current_user=current_user,
                standard_id=series.standard_id,
                academic_year_id=series.academic_year_id,
            )

        entry = await self.repo.create_entry(
            {
                "series_id": series_id,
                "subject_id": body.subject_id,
                "exam_date": body.exam_date,
                "start_time": body.start_time,
                "duration_minutes": body.duration_minutes,
                "venue": body.venue,
                "is_cancelled": False,
            }
        )
        await self.db.refresh(entry)
        return ExamEntryResponse.model_validate(entry)

    async def publish_series(
        self,
        series_id: uuid.UUID,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> ExamSeriesResponse:
        school_id = self._ensure_school(current_user)
        series = await self.repo.get_series_by_id(series_id, school_id)
        if not series:
            raise NotFoundException("Exam series")

        if current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_assigned_standard(
                school_id=school_id,
                current_user=current_user,
                standard_id=series.standard_id,
                academic_year_id=series.academic_year_id,
            )

        if series.is_published:
            return ExamSeriesResponse.model_validate(series)

        updated = await self.repo.update_series(series, {"is_published": True})
        await self.db.refresh(updated)

        background_tasks.add_task(
            _notify_exam_schedule_published,
            school_id,
            series.standard_id,
            series.id,
            series.name,
        )

        return ExamSeriesResponse.model_validate(updated)

    async def cancel_entry(
        self,
        entry_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> ExamEntryResponse:
        school_id = self._ensure_school(current_user)
        entry = await self.repo.get_entry_by_id(entry_id, school_id)
        if not entry:
            raise NotFoundException("Exam schedule entry")

        if current_user.role == RoleEnum.TEACHER:
            series = await self.repo.get_series_by_id(entry.series_id, school_id)
            if not series:
                raise NotFoundException("Exam series")
            await self._assert_teacher_assigned_standard(
                school_id=school_id,
                current_user=current_user,
                standard_id=series.standard_id,
                academic_year_id=series.academic_year_id,
            )

        updated = await self.repo.update_entry(entry, {"is_cancelled": True})
        await self.db.refresh(updated)
        return ExamEntryResponse.model_validate(updated)

    async def get_schedule(
        self,
        standard_id: uuid.UUID,
        series_id: Optional[uuid.UUID],
        current_user: CurrentUser,
    ) -> ExamScheduleTable:
        school_id = self._ensure_school(current_user)

        from app.models.student import Student

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.standard_id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_standard_id = result.scalar_one_or_none()
            if not own_standard_id or own_standard_id != standard_id:
                raise ForbiddenException("You can only view your own class exam schedule")

        elif current_user.role == RoleEnum.PARENT:
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

        elif current_user.role == RoleEnum.TEACHER:
            active_year_id = (await get_active_year(school_id, self.db)).id
            await self._assert_teacher_assigned_standard(
                school_id=school_id,
                current_user=current_user,
                standard_id=standard_id,
                academic_year_id=active_year_id,
            )

        if series_id is None:
            visible_series = await self.repo.list_series(
                school_id=school_id,
                standard_id=standard_id,
                published_only=current_user.role in (RoleEnum.PARENT, RoleEnum.STUDENT),
            )
            if not visible_series:
                raise NotFoundException("Exam series")
            series = visible_series[0]
        else:
            series = await self.repo.get_series_by_id(series_id, school_id)
            if not series or series.standard_id != standard_id:
                raise NotFoundException("Exam series")

        entries = await self.repo.list_entries_for_series(series.id, school_id)
        return ExamScheduleTable(
            series=ExamSeriesResponse.model_validate(series),
            entries=[ExamEntryResponse.model_validate(e) for e in entries],
        )

    async def list_series(
        self,
        *,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
    ) -> list[ExamSeriesResponse]:
        school_id = self._ensure_school(current_user)
        from app.models.student import Student

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.standard_id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_standard_id = result.scalar_one_or_none()
            if not own_standard_id or own_standard_id != standard_id:
                raise ForbiddenException("You can only view your own class exam schedule")
        elif current_user.role == RoleEnum.PARENT:
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
        elif current_user.role == RoleEnum.TEACHER:
            resolved_year_id = academic_year_id or (await get_active_year(school_id, self.db)).id
            await self._assert_teacher_assigned_standard(
                school_id=school_id,
                current_user=current_user,
                standard_id=standard_id,
                academic_year_id=resolved_year_id,
            )

        published_only = current_user.role in (RoleEnum.PARENT, RoleEnum.STUDENT)
        series = await self.repo.list_series(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=academic_year_id,
            published_only=published_only,
        )
        return [ExamSeriesResponse.model_validate(item) for item in series]

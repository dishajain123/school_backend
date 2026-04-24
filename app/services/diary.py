import uuid
import math
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ConflictException, ValidationException
from app.repositories.diary import DiaryRepository
from app.schemas.diary import DiaryCreate, DiaryResponse, DiaryListResponse
from app.services.academic_year import get_active_year
from app.services.assignment import _get_teacher_id, _assert_teacher_owns_class_subject
from app.utils.enums import RoleEnum


class DiaryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DiaryRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    def _to_response(self, entry) -> DiaryResponse:
        subject_name = None
        if getattr(entry, "subject", None) is not None:
            subject_name = getattr(entry.subject, "name", None)

        created_by_name = None
        teacher = getattr(entry, "teacher", None)
        if teacher is not None and getattr(teacher, "user", None) is not None:
            user = teacher.user
            if getattr(user, "full_name", None):
                created_by_name = user.full_name
            elif getattr(user, "email", None):
                created_by_name = user.email
            elif getattr(user, "phone", None):
                created_by_name = user.phone

        base = DiaryResponse.model_validate(entry)
        return base.model_copy(
            update={
                "subject_name": subject_name,
                "created_by_name": created_by_name,
            }
        )

    async def create_entry(
        self,
        body: DiaryCreate,
        current_user: CurrentUser,
    ) -> DiaryResponse:
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
            raise ConflictException("Diary entry already exists for this class and date")

        entry = await self.repo.create(
            {
                "topic_covered": body.topic_covered,
                "homework_note": body.homework_note,
                "date": record_date,
                "teacher_id": teacher_id,
                "standard_id": body.standard_id,
                "subject_id": body.subject_id,
                "academic_year_id": academic_year_id,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(entry)
        return self._to_response(entry)

    async def list_entries(
        self,
        current_user: CurrentUser,
        record_date: Optional[date],
        standard_id: Optional[uuid.UUID],
        subject_id: Optional[uuid.UUID],
        academic_year_id: Optional[uuid.UUID],
        page: int,
        page_size: int,
    ) -> DiaryListResponse:
        school_id = self._ensure_school(current_user)

        resolved_date = record_date
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
                raise ForbiddenException("You can only view diary for your own class")
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

        return DiaryListResponse(
            items=[self._to_response(d) for d in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

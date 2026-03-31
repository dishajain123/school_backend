import uuid
import math
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.student import StudentRepository
from app.schemas.student import StudentCreate, StudentUpdate, StudentPromotionUpdate
from app.models.student import Student
from app.core.dependencies import CurrentUser
from app.core.exceptions import (
    NotFoundException,
    ConflictException,
    ForbiddenException,
)
from app.utils.enums import RoleEnum, PromotionStatus


async def assert_parent_owns_student(
    student: Student,
    current_user: CurrentUser,
) -> None:
    """
    Global scope enforcement helper.
    Reused by every module that a PARENT can call.
    Raises 403 if the parent does not own the student.
    """
    if current_user.role == RoleEnum.PARENT:
        if student.parent_id != current_user.parent_id:
            raise ForbiddenException("You do not have access to this student")


class StudentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = StudentRepository(db)

    async def _get_and_authorize(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Student:
        student = await self.repo.get_by_id(student_id, school_id)
        if not student:
            raise NotFoundException("Student")
        await assert_parent_owns_student(student, current_user)
        return student

    async def create_student(
        self,
        data: StudentCreate,
        school_id: uuid.UUID,
    ) -> Student:
        existing = await self.repo.get_by_admission_number(
            data.admission_number, school_id
        )
        if existing:
            raise ConflictException(
                f"Admission number '{data.admission_number}' already exists in this school"
            )

        if data.user_id:
            existing_user_student = await self.repo.get_by_user_id(data.user_id)
            if existing_user_student:
                raise ConflictException("This user is already linked to another student")

        student = await self.repo.create({
            "user_id": data.user_id,
            "school_id": school_id,
            "parent_id": data.parent_id,
            "standard_id": data.standard_id,
            "academic_year_id": data.academic_year_id,
            "section": data.section,
            "roll_number": data.roll_number,
            "admission_number": data.admission_number,
            "date_of_birth": data.date_of_birth,
            "admission_date": data.admission_date,
            "is_promoted": False,
        })
        return student

    async def get_student(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Student:
        return await self._get_and_authorize(student_id, school_id, current_user)

    async def list_students(
        self,
        school_id: uuid.UUID,
        current_user: CurrentUser,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        academic_year_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Student], int, int]:
        if current_user.role == RoleEnum.PARENT:
            students = await self.repo.list_by_parent(
                current_user.parent_id, school_id
            )
            total = len(students)
            total_pages = 1
            return students, total, total_pages

        if current_user.role == RoleEnum.STUDENT:
            own = await self.repo.get_by_user_id(current_user.id)
            students = [own] if own else []
            return students, len(students), 1

        students, total = await self.repo.list_by_school(
            school_id=school_id,
            standard_id=standard_id,
            section=section,
            academic_year_id=academic_year_id,
            page=page,
            page_size=page_size,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 1
        return students, total, total_pages

    async def update_student(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        data: StudentUpdate,
        current_user: CurrentUser,
    ) -> Student:
        student = await self._get_and_authorize(student_id, school_id, current_user)
        update_data = data.model_dump(exclude_none=True)

        if "user_id" in update_data and update_data["user_id"] != student.user_id:
            existing = await self.repo.get_by_user_id(update_data["user_id"])
            if existing and existing.id != student_id:
                raise ConflictException("This user is already linked to another student")

        return await self.repo.update(student, update_data)

    async def update_promotion_status(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        data: StudentPromotionUpdate,
        current_user: CurrentUser,
    ) -> Student:
        student = await self.repo.get_by_id(student_id, school_id)
        if not student:
            raise NotFoundException("Student")
        # Map status to is_promoted flag
        is_promoted = data.promotion_status == PromotionStatus.PROMOTED
        await self.repo.update_promotion_status(student_id, is_promoted)

        # If held back, record history entry for current year
        if data.promotion_status == PromotionStatus.HELD_BACK:
            from app.repositories.promotion import PromotionRepository
            promo_repo = PromotionRepository(self.db)
            if student.standard_id and student.academic_year_id:
                await promo_repo.create_history(
                    {
                        "student_id": student.id,
                        "standard_id": student.standard_id,
                        "section": student.section,
                        "academic_year_id": student.academic_year_id,
                        "promoted_to_standard_id": None,
                        "promotion_status": PromotionStatus.HELD_BACK,
                        "school_id": school_id,
                    }
                )
                await self.db.commit()

        updated = await self.repo.get_by_id(student_id, school_id)
        return updated

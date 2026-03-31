import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ValidationException, NotFoundException
from app.models.student import Student
from app.models.masters import Standard
from app.models.fee import FeeStructure
from app.repositories.promotion import PromotionRepository
from app.schemas.promotion import RolloverResponse
from app.utils.enums import PromotionStatus


class PromotionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PromotionRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def rollover(
        self,
        old_year_id: uuid.UUID,
        new_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
    ) -> RolloverResponse:
        school_id = self._ensure_school(current_user)

        if not new_year_id:
            from app.repositories.academic_year import AcademicYearRepository
            year_repo = AcademicYearRepository(self.db)
            active = await year_repo.get_active(school_id)
            if not active:
                raise NotFoundException("Active academic year")
            new_year_id = active.id

        if new_year_id == old_year_id:
            raise ValidationException("New academic year must be different from old year")

        # Fetch eligible students for old year
        result = await self.db.execute(
            select(Student).where(
                and_(
                    Student.school_id == school_id,
                    Student.academic_year_id == old_year_id,
                    Student.is_promoted == False,  # noqa: E712
                )
            )
        )
        students = list(result.scalars().all())

        processed = 0
        skipped = 0

        for student in students:
            # Check if held back via latest history record
            latest = await self.repo.get_latest_history(student.id, old_year_id)
            if latest and latest.promotion_status == PromotionStatus.HELD_BACK:
                skipped += 1
                continue

            if not student.standard_id:
                skipped += 1
                continue

            # Find next standard by level
            std_result = await self.db.execute(
                select(Standard).where(
                    and_(
                        Standard.id == student.standard_id,
                        Standard.school_id == school_id,
                    )
                )
            )
            current_standard = std_result.scalar_one_or_none()
            if not current_standard:
                skipped += 1
                continue

            next_std_result = await self.db.execute(
                select(Standard).where(
                    and_(
                        Standard.school_id == school_id,
                        Standard.level == current_standard.level + 1,
                        Standard.academic_year_id == new_year_id,
                    )
                )
            )
            next_standard = next_std_result.scalar_one_or_none()

            await self.repo.create_history(
                {
                    "student_id": student.id,
                    "standard_id": student.standard_id,
                    "section": student.section,
                    "academic_year_id": old_year_id,
                    "promoted_to_standard_id": next_standard.id if next_standard else None,
                    "promotion_status": PromotionStatus.PROMOTED if next_standard else PromotionStatus.HELD_BACK,
                    "school_id": school_id,
                }
            )

            if next_standard:
                student.standard_id = next_standard.id
                student.academic_year_id = new_year_id
                student.is_promoted = True
                processed += 1
            else:
                student.is_promoted = False
                skipped += 1

        # Copy fee structures to new year
        fee_result = await self.db.execute(
            select(FeeStructure).where(
                and_(
                    FeeStructure.school_id == school_id,
                    FeeStructure.academic_year_id == old_year_id,
                )
            )
        )
        structures = list(fee_result.scalars().all())
        for structure in structures:
            dup = await self.db.execute(
                select(FeeStructure.id).where(
                    and_(
                        FeeStructure.school_id == school_id,
                        FeeStructure.academic_year_id == new_year_id,
                        FeeStructure.standard_id == structure.standard_id,
                        FeeStructure.fee_category == structure.fee_category,
                    )
                )
            )
            if dup.scalar_one_or_none():
                continue
            self.db.add(
                FeeStructure(
                    standard_id=structure.standard_id,
                    academic_year_id=new_year_id,
                    fee_category=structure.fee_category,
                    amount=structure.amount,
                    due_date=structure.due_date,
                    description=structure.description,
                    school_id=school_id,
                )
            )

        await self.db.commit()
        return RolloverResponse(processed=processed, skipped=skipped)

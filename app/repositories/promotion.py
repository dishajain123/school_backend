import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student_academic_history import StudentAcademicHistory


class PromotionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_history(self, data: dict) -> StudentAcademicHistory:
        obj = StudentAcademicHistory(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_latest_history(
        self, student_id: uuid.UUID, academic_year_id: uuid.UUID
    ) -> Optional[StudentAcademicHistory]:
        result = await self.db.execute(
            select(StudentAcademicHistory)
            .where(
                and_(
                    StudentAcademicHistory.student_id == student_id,
                    StudentAcademicHistory.academic_year_id == academic_year_id,
                )
            )
            .order_by(StudentAcademicHistory.recorded_at.desc())
        )
        return result.scalars().first()

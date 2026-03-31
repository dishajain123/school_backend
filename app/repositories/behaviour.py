import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student_behaviour_log import StudentBehaviourLog


class BehaviourRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> StudentBehaviourLog:
        obj = StudentBehaviourLog(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def list_by_student(
        self,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> list[StudentBehaviourLog]:
        result = await self.db.execute(
            select(StudentBehaviourLog).where(
                and_(
                    StudentBehaviourLog.school_id == school_id,
                    StudentBehaviourLog.student_id == student_id,
                )
            ).order_by(StudentBehaviourLog.incident_date.desc())
        )
        return list(result.scalars().all())

import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.complaint import Complaint
from app.models.feedback import Feedback
from app.models.user import User
from app.utils.enums import ComplaintCategory, ComplaintStatus, RoleEnum


class ComplaintRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_complaint(self, data: dict) -> Complaint:
        obj = Complaint(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_complaint_by_id(
        self, complaint_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[Complaint]:
        result = await self.db.execute(
            select(Complaint)
            .options(
                selectinload(Complaint.submitter),
                selectinload(Complaint.resolver),
            )
            .where(
                and_(
                    Complaint.id == complaint_id,
                    Complaint.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_complaints(
        self,
        school_id: uuid.UUID,
        status: Optional[ComplaintStatus] = None,
        category: Optional[ComplaintCategory] = None,
        submitted_by_role: Optional[RoleEnum] = None,
        submitted_by: Optional[uuid.UUID] = None,
    ) -> list[Complaint]:
        stmt = (
            select(Complaint)
            .options(
                selectinload(Complaint.submitter),
                selectinload(Complaint.resolver),
            )
            .where(Complaint.school_id == school_id)
        )
        if status:
            stmt = stmt.where(Complaint.status == status)
        if category:
            stmt = stmt.where(Complaint.category == category)
        if submitted_by_role:
            stmt = stmt.join(User, Complaint.submitted_by == User.id).where(
                User.role == submitted_by_role
            )
        if submitted_by:
            stmt = stmt.where(Complaint.submitted_by == submitted_by)
        stmt = stmt.order_by(Complaint.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_complaint(self, complaint: Complaint, data: dict) -> Complaint:
        for key, value in data.items():
            setattr(complaint, key, value)
        await self.db.flush()
        await self.db.refresh(complaint)
        return complaint

    # Feedback
    async def create_feedback(self, data: dict) -> Feedback:
        obj = Feedback(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

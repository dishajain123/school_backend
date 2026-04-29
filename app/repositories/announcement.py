import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.announcement import Announcement
from app.utils.enums import RoleEnum


class AnnouncementRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Announcement:
        obj = Announcement(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, announcement_id: uuid.UUID, school_id: uuid.UUID) -> Optional[Announcement]:
        result = await self.db.execute(
            select(Announcement).where(
                and_(
                    Announcement.id == announcement_id,
                    Announcement.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_for_school(
        self,
        school_id: uuid.UUID,
        include_inactive: bool = False,
        target_role: Optional[RoleEnum] = None,
        target_standard_id: Optional[uuid.UUID] = None,
    ) -> list[Announcement]:
        stmt = select(Announcement).where(Announcement.school_id == school_id)
        if not include_inactive:
            stmt = stmt.where(Announcement.is_active == True)  # noqa: E712
        if target_role is not None:
            stmt = stmt.where(Announcement.target_role == target_role)
        if target_standard_id is not None:
            stmt = stmt.where(Announcement.target_standard_id == target_standard_id)
        stmt = stmt.order_by(Announcement.published_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(self, announcement: Announcement, data: dict) -> Announcement:
        for key, value in data.items():
            setattr(announcement, key, value)
        await self.db.flush()
        await self.db.refresh(announcement)
        return announcement

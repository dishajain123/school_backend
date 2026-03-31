import uuid
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.parent import Parent
from app.models.student import Student


class ParentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Parent:
        parent = Parent(**data)
        self.db.add(parent)
        await self.db.flush()
        await self.db.refresh(parent)
        return parent

    async def get_by_id(self, parent_id: uuid.UUID, school_id: uuid.UUID) -> Optional[Parent]:
        result = await self.db.execute(
            select(Parent)
            .options(selectinload(Parent.user))
            .where(
                Parent.id == parent_id,
                Parent.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID) -> Optional[Parent]:
        result = await self.db.execute(
            select(Parent)
            .options(selectinload(Parent.user))
            .where(Parent.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_raw(self, parent_id: uuid.UUID) -> Optional[Parent]:
        """Fetch without school_id filter — used internally."""
        result = await self.db.execute(
            select(Parent)
            .options(selectinload(Parent.user))
            .where(Parent.id == parent_id)
        )
        return result.scalar_one_or_none()

    async def list_by_school(
        self,
        school_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Parent], int]:
        base = select(Parent).where(Parent.school_id == school_id)
        count_q = select(func.count(Parent.id)).where(Parent.school_id == school_id)

        total = (await self.db.execute(count_q)).scalar_one()

        offset = (page - 1) * page_size
        rows = await self.db.execute(
            base.options(selectinload(Parent.user))
            .order_by(Parent.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(rows.scalars().all()), total

    async def update(self, parent: Parent, data: dict) -> Parent:
        for key, value in data.items():
            setattr(parent, key, value)
        await self.db.flush()
        await self.db.refresh(parent)
        return parent

    async def get_children(self, parent_id: uuid.UUID, school_id: uuid.UUID) -> list[Student]:
        result = await self.db.execute(
            select(Student).where(
                Student.parent_id == parent_id,
                Student.school_id == school_id,
            )
        )
        return list(result.scalars().all())
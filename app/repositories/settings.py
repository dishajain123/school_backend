import uuid
from typing import Optional

from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.school_settings import SchoolSetting


class SettingsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_school(self, school_id: uuid.UUID) -> list[SchoolSetting]:
        result = await self.db.execute(
            select(SchoolSetting).where(SchoolSetting.school_id == school_id)
        )
        return list(result.scalars().all())

    async def get_by_key(
        self, school_id: uuid.UUID, key: str
    ) -> Optional[SchoolSetting]:
        result = await self.db.execute(
            select(SchoolSetting).where(
                SchoolSetting.school_id == school_id,
                SchoolSetting.setting_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_settings(
        self,
        school_id: uuid.UUID,
        items: list[dict],
        updated_by: Optional[uuid.UUID],
    ) -> None:
        if not items:
            return
        stmt = pg_insert(SchoolSetting).values(
            [
                {
                    "school_id": school_id,
                    "setting_key": item["key"],
                    "setting_value": item["value"],
                    "updated_by": updated_by,
                }
                for item in items
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["school_id", "setting_key"],
            set_={
                "setting_value": stmt.excluded.setting_value,
                "updated_by": stmt.excluded.updated_by,
            },
        )
        await self.db.execute(stmt)
        await self.db.flush()

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.jti_blocklist import JtiBlocklist


class JtiBlocklistRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, jti: str, user_id: uuid.UUID, expires_at: datetime) -> JtiBlocklist:
        entry = JtiBlocklist(
            jti=jti,
            user_id=user_id,
            expires_at=expires_at,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def is_blocked(self, jti: str) -> bool:
        result = await self.db.execute(
            select(JtiBlocklist).where(JtiBlocklist.jti == jti)
        )
        return result.scalar_one_or_none() is not None

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        from sqlalchemy import update
        existing = await self.db.execute(
            select(JtiBlocklist).where(JtiBlocklist.user_id == user_id)
        )
        pass

    async def purge_expired(self) -> int:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            delete(JtiBlocklist).where(JtiBlocklist.expires_at < now)
        )
        await self.db.flush()
        return result.rowcount
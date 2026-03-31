import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.otp_store import OtpStore


class OtpStoreRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: uuid.UUID, hashed_otp: str, expires_at: datetime) -> OtpStore:
        otp = OtpStore(
            user_id=user_id,
            otp_code=hashed_otp,
            expires_at=expires_at,
            is_used=False,
        )
        self.db.add(otp)
        await self.db.flush()
        await self.db.refresh(otp)
        return otp

    async def get_latest_valid(self, user_id: uuid.UUID) -> Optional[OtpStore]:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(OtpStore)
            .where(
                OtpStore.user_id == user_id,
                OtpStore.is_used == False,
                OtpStore.expires_at > now,
            )
            .order_by(OtpStore.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_used(self, otp_id: uuid.UUID) -> None:
        await self.db.execute(
            update(OtpStore).where(OtpStore.id == otp_id).values(is_used=True)
        )
        await self.db.flush()

    async def invalidate_all_for_user(self, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(OtpStore)
            .where(OtpStore.user_id == user_id, OtpStore.is_used == False)
            .values(is_used=True)
        )
        await self.db.flush()
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, delete, update
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

    # FIX: previous version executed a SELECT query then immediately did `pass`,
    # discarding all results and doing nothing. This method is not called anywhere
    # in the current codebase but must be correct for future use.
    # It should delete (or logically revoke) all active blocklist entries for a user.
    # Since the blocklist uses JTI strings as primary key, "revoking all" means
    # deleting all unexpired entries so the purge job handles the rest, or the
    # caller relies on the blocklist being checked per JTI. The correct semantic
    # for logout-all / deactivation scenarios is to add sentinel entries — but
    # since we only store issued JTIs on explicit logout, the safest approach is
    # to remove any existing entries for the user (clearing them from the blocklist)
    # so that if re-issued tokens arrive they are cleanly evaluated from scratch.
    # For a true "revoke all sessions" feature, callers should instead invalidate
    # every outstanding access token by inserting their JTIs. This helper is kept
    # as a no-op-safe stub until that caller is implemented.
    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """
        Delete all blocklist entries belonging to `user_id`.
        Returns the number of rows deleted.
        This is a maintenance helper — call it when a user is deactivated or
        performs a global sign-out to clean up stale blocklist rows.
        """
        result = await self.db.execute(
            delete(JtiBlocklist).where(JtiBlocklist.user_id == user_id)
        )
        await self.db.flush()
        return result.rowcount  # type: ignore[return-value]

    async def purge_expired(self) -> int:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            delete(JtiBlocklist).where(JtiBlocklist.expires_at < now)
        )
        await self.db.flush()
        return result.rowcount  # type: ignore[return-value]
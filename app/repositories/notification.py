import uuid
from typing import Optional
from sqlalchemy import select, func, update, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.utils.enums import NotificationType, NotificationPriority


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Notification:
        obj = Notification(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Optional[Notification]:
        result = await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        is_read: Optional[bool] = None,
        type_filter: Optional[NotificationType] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Notification], int, int]:
        base = select(Notification).where(Notification.user_id == user_id)
        count_q = select(func.count(Notification.id)).where(Notification.user_id == user_id)
        unread_q = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )

        if is_read is not None:
            base = base.where(Notification.is_read == is_read)
            count_q = count_q.where(Notification.is_read == is_read)

        if type_filter is not None:
            base = base.where(Notification.type == type_filter)
            count_q = count_q.where(Notification.type == type_filter)

        total = (await self.db.execute(count_q)).scalar_one()
        unread_count = (await self.db.execute(unread_q)).scalar_one()

        offset = (page - 1) * page_size
        rows = await self.db.execute(
            base.order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(rows.scalars().all()), total, unread_count

    async def mark_read(
        self,
        notification_ids: list[uuid.UUID],
        user_id: uuid.UUID,
    ) -> int:
        result = await self.db.execute(
            update(Notification)
            .where(
                and_(
                    Notification.id.in_(notification_ids),
                    Notification.user_id == user_id,
                )
            )
            .values(is_read=True)
        )
        await self.db.flush()
        return result.rowcount  # type: ignore[return-value]

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
            .values(is_read=True)
        )
        await self.db.flush()
        return result.rowcount  # type: ignore[return-value]

    async def delete_read(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            delete(Notification).where(
                Notification.user_id == user_id,
                Notification.is_read == True,  # noqa: E712
            )
        )
        await self.db.flush()
        return result.rowcount  # type: ignore[return-value]

    async def purge_old(self, cutoff_days: int = 90) -> int:
        """Called by APScheduler cleanup job — deletes read notifications older than cutoff."""
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
        result = await self.db.execute(
            delete(Notification).where(
                Notification.is_read == True,  # noqa: E712
                Notification.created_at < cutoff,
            )
        )
        await self.db.flush()
        return result.rowcount  # type: ignore[return-value]

    async def unread_count_for_user(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
        )
        return result.scalar_one()
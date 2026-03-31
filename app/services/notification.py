import uuid
import math
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notification import NotificationRepository
from app.schemas.notification import NotificationCreate, MarkReadRequest
from app.models.notification import Notification
from app.core.exceptions import ValidationException
from app.core.dependencies import CurrentUser
from app.utils.enums import NotificationType, NotificationPriority


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NotificationRepository(db)

    # ── Internal writer — called via BackgroundTask from other services ───────

    async def create(
        self,
        user_id: uuid.UUID,
        title: str,
        body: str,
        type: NotificationType,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        reference_id: Optional[uuid.UUID] = None,
    ) -> Notification:
        """
        Fire-and-forget writer used by all other modules:

            background_tasks.add_task(
                notification_service.create,
                user_id=...,
                title=...,
                body=...,
                type=NotificationType.ATTENDANCE,
                priority=NotificationPriority.HIGH,
            )
        """
        obj = await self.repo.create(
            {
                "user_id": user_id,
                "title": title,
                "body": body,
                "type": type,
                "priority": priority,
                "reference_id": reference_id,
            }
        )
        await self.db.commit()
        return obj

    # ── Inbox ─────────────────────────────────────────────────────────────────

    async def get_inbox(
        self,
        current_user: CurrentUser,
        is_read: Optional[bool],
        type_filter: Optional[NotificationType],
        page: int,
        page_size: int,
    ) -> dict:
        items, total, unread_count = await self.repo.list_for_user(
            user_id=current_user.id,
            is_read=is_read,
            type_filter=type_filter,
            page=page,
            page_size=page_size,
        )
        return {
            "items": items,
            "total": total,
            "unread_count": unread_count,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total else 0,
        }

    # ── Mark read ─────────────────────────────────────────────────────────────

    async def mark_read(
        self,
        payload: MarkReadRequest,
        current_user: CurrentUser,
    ) -> dict:
        if not payload.ids:
            raise ValidationException("At least one notification id is required")

        updated = await self.repo.mark_read(payload.ids, current_user.id)
        await self.db.commit()
        return {"updated": updated, "message": f"{updated} notification(s) marked as read"}

    async def mark_all_read(self, current_user: CurrentUser) -> dict:
        updated = await self.repo.mark_all_read(current_user.id)
        await self.db.commit()
        return {"updated": updated, "message": f"{updated} notification(s) marked as read"}

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def clear_read(self, current_user: CurrentUser) -> dict:
        deleted = await self.repo.delete_read(current_user.id)
        await self.db.commit()
        return {"deleted": deleted, "message": f"{deleted} read notification(s) cleared"}

    async def purge_old_notifications(self, cutoff_days: int = 90) -> dict:
        """Called by APScheduler — not an API endpoint."""
        deleted = await self.repo.purge_old(cutoff_days)
        await self.db.commit()
        return {"deleted": deleted}

    # ── Unread count (lightweight — for badge counters) ───────────────────────

    async def get_unread_count(self, current_user: CurrentUser) -> dict:
        count = await self.repo.unread_count_for_user(current_user.id)
        return {"unread_count": count}
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.utils.enums import AuditAction


class AuditLogService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        action: AuditAction,
        actor_id: Optional[uuid.UUID],
        target_user_id: Optional[uuid.UUID],
        entity_type: str,
        entity_id: Optional[str] = None,
        description: str = "",
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        school_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        record = AuditLog(
            school_id=school_id,
            actor_id=actor_id,
            target_user_id=target_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            before_state=before_state,
            after_state=after_state,
            ip_address=ip_address,
        )
        self.db.add(record)
        await self.db.flush()
        return record

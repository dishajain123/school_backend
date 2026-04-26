from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.utils.enums import ApprovalAction, UserStatus


class UserApprovalAudit(BaseModel):
    __tablename__ = "user_approval_audits"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    acted_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action: Mapped[ApprovalAction] = mapped_column(
        SQLEnum(ApprovalAction, name="approvalaction"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[Optional[UserStatus]] = mapped_column(
        SQLEnum(UserStatus, name="userstatus", create_type=False),
        nullable=True,
    )
    to_status: Mapped[Optional[UserStatus]] = mapped_column(
        SQLEnum(UserStatus, name="userstatus", create_type=False),
        nullable=True,
    )
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    validation_issues: Mapped[Optional[list[dict]]] = mapped_column(JSONB, nullable=True)
    duplicate_matches: Mapped[Optional[list[dict]]] = mapped_column(JSONB, nullable=True)
    acted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="select")
    acted_by: Mapped["User"] = relationship("User", foreign_keys=[acted_by_id], lazy="select")

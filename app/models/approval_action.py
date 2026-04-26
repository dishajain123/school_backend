# app/models/approval_action.py

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import BaseModel
from app.utils.enums import ApprovalDecision


class ApprovalAction(BaseModel):
    """
    Immutable record of every decision made on a registration.
    Full audit trail — never updated, only inserted.
    """
    __tablename__ = "approval_actions"

    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registration_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,  # system actions have no actor
    )
    decision: Mapped[ApprovalDecision] = mapped_column(
        String(20), nullable=False
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    # Relationships
    registration: Mapped["RegistrationRequest"] = relationship(
        "RegistrationRequest", back_populates="actions"
    )
    actor: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[actor_id]
    )
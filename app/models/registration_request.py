# app/models/registration_request.py

import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel
from app.utils.enums import UserStatus, RegistrationSource, RoleEnum


class RegistrationRequest(BaseModel):
    """
    Snapshot of registration data submitted by user or created by admin.
    Immutable after creation — all decisions reference this record.
    """
    __tablename__ = "registration_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,          # one request per user
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_requested: Mapped[RoleEnum] = mapped_column(
        String(50), nullable=False
    )
    registration_source: Mapped[RegistrationSource] = mapped_column(
        String(50), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Role-specific submitted data stored as JSONB
    submitted_data: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )

    # Flags
    has_duplicates: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    duplicate_details: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )
    data_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    missing_fields: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True
    )

    current_status: Mapped[UserStatus] = mapped_column(
        String(50), nullable=False, default=UserStatus.PENDING_APPROVAL
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    school: Mapped["School"] = relationship("School", foreign_keys=[school_id])
    actions: Mapped[list["ApprovalAction"]] = relationship(
        "ApprovalAction", back_populates="registration", cascade="all, delete"
    )
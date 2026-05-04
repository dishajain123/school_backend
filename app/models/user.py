from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel
from app.utils.enums import RoleEnum, UserStatus, RegistrationSource


class User(BaseModel):
    __tablename__ = "users"

    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True, index=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[RoleEnum] = mapped_column(
        SQLEnum(RoleEnum, name="roleenum", create_type=False),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Phase 1 onboarding state
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus, name="userstatus"),
        nullable=False,
        default=UserStatus.PENDING_APPROVAL,
        index=True,
    )
    registration_source: Mapped[RegistrationSource] = mapped_column(
        SQLEnum(RegistrationSource, name="registrationsource"),
        nullable=False,
        default=RegistrationSource.SELF_REGISTERED,
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    hold_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    submitted_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    approved_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # NOTE: is_active remains, but should be driven by status in service logic.
    # Expected: is_active=True only when status=ACTIVE.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    profile_photo_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    school: Mapped["School"] = relationship("School", foreign_keys=[school_id], lazy="select")

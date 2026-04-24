from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy import String, Boolean, Enum as SAEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel
from app.utils.enums import RoleEnum


class User(BaseModel):
    __tablename__ = "users"

    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True, index=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[RoleEnum] = mapped_column(
        SAEnum(RoleEnum, name="roleenum", create_type=False),
        nullable=False,
    )
    school_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    profile_photo_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    school: Mapped[Optional["School"]] = relationship("School", foreign_keys=[school_id], lazy="select")

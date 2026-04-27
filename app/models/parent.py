from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, Enum as SAEnum, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel
from app.utils.enums import RelationType


class Parent(BaseModel):
    __tablename__ = "parents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_code: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, unique=False, index=True
    )
    identifier_issued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_identifier_custom: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    occupation: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    relation: Mapped[RelationType] = mapped_column(
        SAEnum(RelationType, name="relationtype", create_type=False),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="select")
    school: Mapped["School"] = relationship("School", foreign_keys=[school_id], lazy="select")
    children: Mapped[list["Student"]] = relationship(
        "Student",
        foreign_keys="Student.parent_id",
        lazy="select",
        back_populates="parent",
    )

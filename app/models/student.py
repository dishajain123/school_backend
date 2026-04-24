from __future__ import annotations

import uuid
import re
from datetime import date
from typing import Optional
from sqlalchemy import String, Boolean, ForeignKey, Date, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel


class Student(BaseModel):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("admission_number", "school_id", name="uq_student_admission_school"),
    )

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    standard_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    academic_year_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    section: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    roll_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    admission_number: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    admission_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_promoted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[user_id], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
    parent: Mapped["Parent"] = relationship(
        "Parent", foreign_keys=[parent_id], lazy="select"
    )
    standard: Mapped[Optional["Standard"]] = relationship(
        "Standard", foreign_keys=[standard_id], lazy="select"
    )
    academic_year: Mapped[Optional["AcademicYear"]] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )

    @property
    def student_name(self) -> Optional[str]:
        if self.user and self.user.full_name and self.user.full_name.strip():
            return self.user.full_name.strip()
        # Derive a readable label from linked user email when explicit names are unavailable.
        if self.user and self.user.email:
            local = self.user.email.split("@", 1)[0]
            cleaned = re.sub(r"[\._\-]+", " ", local).strip()
            if cleaned:
                return " ".join(word.capitalize() for word in cleaned.split())
        return None

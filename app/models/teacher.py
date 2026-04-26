from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, Date, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym
from app.db.base import BaseModel


class Teacher(BaseModel):
    __tablename__ = "teachers"

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
    academic_year_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    employee_id: Mapped[str] = mapped_column(
        "employee_code",
        String(50),
        nullable=False,
        unique=True,
        index=True,
    )
    employee_code = synonym("employee_id")
    identifier_issued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_identifier_custom: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    join_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    specialization: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    user: Mapped["User"] = relationship(
        "User", foreign_keys=[user_id], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
    academic_year: Mapped[Optional["AcademicYear"]] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )

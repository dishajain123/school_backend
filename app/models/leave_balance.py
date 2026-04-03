from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Numeric, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.utils.enums import LeaveType

if TYPE_CHECKING:
    from app.models.teacher import Teacher
    from app.models.academic_year import AcademicYear
    from app.models.school import School


class LeaveBalance(BaseModel):
    __tablename__ = "leave_balance"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id",
            "academic_year_id",
            "leave_type",
            name="uq_leave_balance_teacher_year_type",
        ),
    )

    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    leave_type: Mapped[LeaveType] = mapped_column(
        Enum(LeaveType, name="leave_type_enum"),
        nullable=False,
    )
    total_days: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    used_days: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    teacher: Mapped["Teacher"] = relationship(
        "Teacher", foreign_keys=[teacher_id], lazy="select"
    )
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )

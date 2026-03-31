import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.utils.enums import PromotionStatus

if TYPE_CHECKING:
    from app.models.student import Student
    from app.models.masters import Standard
    from app.models.academic_year import AcademicYear
    from app.models.school import School


class StudentAcademicHistory(BaseModel):
    __tablename__ = "student_academic_history"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    promoted_to_standard_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    promotion_status: Mapped[PromotionStatus] = mapped_column(
        Enum(PromotionStatus, name="promotion_status_enum"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    student: Mapped["Student"] = relationship(
        "Student", foreign_keys=[student_id], lazy="select"
    )
    standard: Mapped["Standard"] = relationship(
        "Standard", foreign_keys=[standard_id], lazy="select"
    )
    promoted_to_standard: Mapped[Optional["Standard"]] = relationship(
        "Standard", foreign_keys=[promoted_to_standard_id], lazy="select"
    )
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )

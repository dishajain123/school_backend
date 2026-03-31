import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Date, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.utils.enums import ExamType

if TYPE_CHECKING:
    from app.models.masters import Standard
    from app.models.academic_year import AcademicYear
    from app.models.school import School
    from app.models.user import User
    from app.models.result import Result


class Exam(BaseModel):
    __tablename__ = "exams"
    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "standard_id",
            "academic_year_id",
            "name",
            name="uq_exam_name_standard_year_school",
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    exam_type: Mapped[ExamType] = mapped_column(
        Enum(ExamType, name="exam_type_enum"),
        nullable=False,
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    standard: Mapped["Standard"] = relationship(
        "Standard", foreign_keys=[standard_id], lazy="select"
    )
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
    creator: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[created_by], lazy="select"
    )
    results: Mapped[list["Result"]] = relationship(
        "Result", back_populates="exam", lazy="select"
    )

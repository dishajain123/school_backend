import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Date, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel

if TYPE_CHECKING:
    from app.models.masters import Standard
    from app.models.academic_year import AcademicYear
    from app.models.school import School
    from app.models.user import User


class Timetable(BaseModel):
    __tablename__ = "timetables"
    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "standard_id",
            "section",
            "academic_year_id",
            name="uq_timetable_standard_section_year_school",
        ),
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
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    effective_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
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
    uploader: Mapped["User"] = relationship(
        "User", foreign_keys=[uploaded_by], lazy="select"
    )
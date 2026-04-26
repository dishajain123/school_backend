# app/models/section.py
"""
Section is now a first-class entity.
Replaces the JSONB section registry with a proper normalized table.
JSONB registry can remain for legacy reads — sections table is the source of truth.
"""
import uuid
from sqlalchemy import String, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel


class Section(BaseModel):
    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint(
            "school_id", "standard_id", "academic_year_id", "name",
            name="uq_section_school_std_year_name",
        ),
    )

    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    # Section name: "A", "B", "C", etc. — always stored UPPERCASE
    name: Mapped[str] = mapped_column(String(10), nullable=False)

    # Soft state — section can be deactivated without deleting (students may exist)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Capacity hint (optional — used for enrollment limits in Phase 6)
    capacity: Mapped[int] = mapped_column(
        __import__('sqlalchemy').Integer, nullable=True
    )

    # Relationships
    standard: Mapped["Standard"] = relationship("Standard", foreign_keys=[standard_id])
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id]
    )
    school: Mapped["School"] = relationship("School", foreign_keys=[school_id])
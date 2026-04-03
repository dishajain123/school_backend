from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Date, Numeric, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.utils.enums import FeeCategory, FeeStatus

if TYPE_CHECKING:
    from app.models.masters import Standard
    from app.models.academic_year import AcademicYear
    from app.models.school import School
    from app.models.student import Student
    from app.models.payment import Payment


class FeeStructure(BaseModel):
    __tablename__ = "fee_structures"
    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "standard_id",
            "academic_year_id",
            "fee_category",
            name="uq_fee_structure_category_standard_year_school",
        ),
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
    fee_category: Mapped[FeeCategory] = mapped_column(
        Enum(FeeCategory, name="fee_category_enum"),
        nullable=False,
        index=True,
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
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
    ledgers: Mapped[list["FeeLedger"]] = relationship(
        "FeeLedger", back_populates="fee_structure", lazy="select"
    )


class FeeLedger(BaseModel):
    __tablename__ = "fee_ledger"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fee_structure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fee_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    paid_amount: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, server_default="0"
    )
    status: Mapped[FeeStatus] = mapped_column(
        Enum(FeeStatus, name="fee_status_enum"),
        nullable=False,
        default=FeeStatus.PENDING,
        server_default=FeeStatus.PENDING.value,
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
    fee_structure: Mapped["FeeStructure"] = relationship(
        "FeeStructure", foreign_keys=[fee_structure_id], back_populates="ledgers", lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="fee_ledger", lazy="select"
    )

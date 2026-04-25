from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.utils.enums import PaymentMode

if TYPE_CHECKING:
    from app.models.fee import FeeLedger
    from app.models.student import Student
    from app.models.school import School
    from app.models.user import User


class Payment(BaseModel):
    __tablename__ = "payments"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fee_ledger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fee_ledger.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payment_mode: Mapped[PaymentMode] = mapped_column(
        SAEnum(PaymentMode, name="payment_mode_enum"),
        nullable=False,
    )
    reference_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # transaction_ref is an alias / extended field for external transaction IDs
    transaction_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    receipt_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    recorded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    late_fee_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    original_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    student: Mapped["Student"] = relationship(
        "Student", foreign_keys=[student_id], lazy="select"
    )
    fee_ledger: Mapped["FeeLedger"] = relationship(
        "FeeLedger", foreign_keys=[fee_ledger_id], back_populates="payments", lazy="select"
    )
    recorded_by_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[recorded_by], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
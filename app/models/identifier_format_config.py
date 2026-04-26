# app/models/identifier_format_config.py
"""
Per-school, per-identifier-type format rules.
Super Admin defines the format. Admins cannot change it once identifiers are issued.
"""
import uuid
from typing import Optional
from sqlalchemy import String, Integer, Boolean, UniqueConstraint, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel


class IdentifierFormatConfig(BaseModel):
    __tablename__ = "identifier_format_configs"
    __table_args__ = (
        UniqueConstraint(
            "school_id", "identifier_type",
            name="uq_identifier_format_school_type",
        ),
    )

    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    identifier_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Format template — tokens:
    #   {YEAR}   → current 4-digit year (students only)
    #   {SEQ}    → zero-padded sequence number
    # Examples:
    #   "{YEAR}/{SEQ}"  → "2024/0001"
    #   "EMP/{SEQ}"     → "EMP/0042"
    #   "PAR-{SEQ}"     → "PAR-0017"
    format_template: Mapped[str] = mapped_column(
        String(100), nullable=False, default="{YEAR}/{SEQ}"
    )

    # How many digits to pad the sequence: 4 → 0001, 5 → 00001
    sequence_padding: Mapped[int] = mapped_column(Integer, nullable=False, default=4)

    # Whether sequence resets each new year (true for students, false for staff)
    reset_yearly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Lock — once at least one identifier of this type is issued, format is frozen
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Optional prefix override (replaces {PREFIX} token if used)
    prefix: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    configured_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
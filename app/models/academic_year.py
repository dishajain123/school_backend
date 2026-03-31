import uuid
from datetime import date
from sqlalchemy import String, Boolean, ForeignKey, Date, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel


class AcademicYear(BaseModel):
    __tablename__ = "academic_years"
    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_academic_year_school_name"),
    )

    name: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    school: Mapped["School"] = relationship("School", foreign_keys=[school_id], lazy="select")
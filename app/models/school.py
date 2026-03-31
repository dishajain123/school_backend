import uuid
from sqlalchemy import String, Text, Boolean, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import BaseModel
from app.utils.enums import SubscriptionPlan


class School(BaseModel):
    __tablename__ = "schools"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    subscription_plan: Mapped[SubscriptionPlan] = mapped_column(
        SAEnum(SubscriptionPlan, name="subscriptionplan", create_type=False),
        nullable=False,
        default=SubscriptionPlan.BASIC,
        server_default=SubscriptionPlan.BASIC.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
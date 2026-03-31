import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.utils.enums import SubscriptionPlan


class SchoolBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    address: Optional[str] = None
    contact_email: EmailStr
    contact_phone: Optional[str] = Field(None, max_length=20)
    subscription_plan: SubscriptionPlan = SubscriptionPlan.BASIC


class SchoolCreate(SchoolBase):
    pass


class SchoolUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    address: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, max_length=20)
    subscription_plan: Optional[SubscriptionPlan] = None


class SchoolResponse(SchoolBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SchoolListResponse(BaseModel):
    items: list[SchoolResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
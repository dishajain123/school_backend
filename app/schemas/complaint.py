import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.utils.enums import ComplaintCategory, ComplaintStatus, FeedbackType, RoleEnum


class ComplaintCreate(BaseModel):
    category: ComplaintCategory
    description: str
    is_anonymous: bool = False
    attachment_key: Optional[str] = None

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description cannot be empty")
        return v


class ComplaintStatusUpdate(BaseModel):
    status: ComplaintStatus
    resolution_note: Optional[str] = None


class ComplaintResponse(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    submitted_by: Optional[uuid.UUID] = None
    submitted_by_name: Optional[str] = None
    submitted_by_role: Optional[RoleEnum] = None
    category: ComplaintCategory
    description: str
    attachment_key: Optional[str] = None
    attachment_url: Optional[str] = None
    status: ComplaintStatus
    resolved_by: Optional[uuid.UUID] = None
    resolution_note: Optional[str] = None
    is_anonymous: bool
    created_at: datetime
    created_at_local: Optional[str] = None

    model_config = {"from_attributes": True}


class ComplaintListResponse(BaseModel):
    items: list[ComplaintResponse]
    total: int


class FeedbackCreate(BaseModel):
    feedback_type: FeedbackType
    rating: int
    comment: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_range(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("Rating must be between 1 and 5")
        return v


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    feedback_type: FeedbackType
    rating: int
    comment: Optional[str] = None
    created_at: datetime
    school_id: uuid.UUID

    model_config = {"from_attributes": True}

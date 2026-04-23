import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.utils.enums import RoleEnum


class AlbumCreate(BaseModel):
    event_name: str
    event_date: date
    description: Optional[str] = None
    academic_year_id: Optional[uuid.UUID] = None

    @field_validator("event_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Event name cannot be empty")
        return v


class AlbumResponse(BaseModel):
    id: uuid.UUID
    event_name: str
    event_date: date
    description: Optional[str] = None
    cover_photo_key: Optional[str] = None
    cover_photo_url: Optional[str] = None
    created_by: Optional[uuid.UUID] = None
    school_id: uuid.UUID
    academic_year_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlbumListResponse(BaseModel):
    items: list[AlbumResponse]
    total: int


class PhotoResponse(BaseModel):
    id: uuid.UUID
    album_id: uuid.UUID
    photo_key: str
    photo_url: Optional[str] = None
    caption: Optional[str] = None
    uploaded_by: Optional[uuid.UUID] = None
    uploaded_at: datetime
    is_featured: bool
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PhotoListResponse(BaseModel):
    items: list[PhotoResponse]
    total: int


class PhotoCommentCreate(BaseModel):
    comment: str = Field(..., max_length=1000)

    @field_validator("comment")
    @classmethod
    def comment_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Comment cannot be empty")
        return v


class PhotoCommentResponse(BaseModel):
    id: uuid.UUID
    photo_id: uuid.UUID
    comment: str
    commented_by: uuid.UUID
    commenter_role: RoleEnum
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PhotoInteractionResponse(BaseModel):
    photo_id: uuid.UUID
    reactions_count: int = 0
    has_reacted: bool = False
    comments: list[PhotoCommentResponse] = Field(default_factory=list)
    total_comments: int = 0

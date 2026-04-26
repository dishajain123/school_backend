import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from app.utils.enums import RegistrationSource, RoleEnum, UserStatus


class UserCreate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    password: str = Field(..., min_length=8)
    role: RoleEnum
    is_active: bool = True

    model_config = {"str_strip_whitespace": True}


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None

    model_config = {"str_strip_whitespace": True}


class UserResponse(BaseModel):
    id: uuid.UUID
    full_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    role: RoleEnum
    school_id: Optional[uuid.UUID]
    status: UserStatus
    registration_source: RegistrationSource
    is_active: bool
    profile_photo_key: Optional[str]
    profile_photo_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class UserPhotoResponse(BaseModel):
    profile_photo_key: str
    profile_photo_url: str
    message: str


class UserMeUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = Field(None, max_length=20)

    model_config = {"str_strip_whitespace": True}

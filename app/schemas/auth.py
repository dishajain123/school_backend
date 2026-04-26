import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from app.utils.enums import RoleEnum, UserStatus


class LoginRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: str = Field(..., min_length=1)

    model_config = {"str_strip_whitespace": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


class VerifyOtpRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    otp_code: str = Field(..., min_length=6, max_length=6)


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(..., min_length=8)


class ForgotPasswordResponse(BaseModel):
    message: str
    hint: Optional[str] = None


class VerifyOtpResponse(BaseModel):
    reset_token: str
    expires_in: int
    message: str


class ResetPasswordResponse(BaseModel):
    message: str


class CurrentUserSchema(BaseModel):
    id: uuid.UUID
    role: RoleEnum
    school_id: Optional[uuid.UUID]
    parent_id: Optional[uuid.UUID]
    permissions: list[str]
    full_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    status: UserStatus
    is_active: bool

import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth import AuthService
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    AccessTokenResponse,
    LogoutRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    CurrentUserSchema,
)
from app.core.dependencies import get_current_user, CurrentUser
from app.core.security import decode_token

router = APIRouter(prefix="/auth", tags=["Authentication"])


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.login(
        email=str(data.email).lower().strip() if data.email else None,
        phone=data.phone,
        password=data.password,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_token(
    data: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.refresh_token(data.refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    data: LogoutRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").replace("bearer ", "").strip()

    payload = decode_token(token)
    jti = payload.get("jti")
    exp = payload.get("exp", 0)

    await service.logout(
        access_token_jti=jti,
        access_token_exp=exp,
        user_id=current_user.id,
        refresh_token=data.refresh_token,
    )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    data: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.forgot_password(
        email=str(data.email).lower().strip() if data.email else None,
        phone=data.phone,
    )


@router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp(
    data: VerifyOtpRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.verify_otp(
        email=str(data.email).lower().strip() if data.email else None,
        phone=data.phone,
        otp_code=data.otp_code,
    )


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    data: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.reset_password(data.reset_token, data.new_password)


@router.get("/me", response_model=CurrentUserSchema)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.repositories.user import UserRepository
    repo = UserRepository(db)
    user = await repo.get_by_id(current_user.id)
    return CurrentUserSchema(
        id=current_user.id,
        role=current_user.role,
        school_id=current_user.school_id,
        parent_id=current_user.parent_id,
        permissions=current_user.permissions,
        email=user.email if user else current_user.email,
        phone=user.phone if user else current_user.phone,
        is_active=user.is_active if user else current_user.is_active,
    )
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
from app.core.security import decode_token, extract_bearer_token
from app.core.exceptions import UnauthorizedException
from app.models.parent import Parent
from app.models.student import Student
from app.models.student_year_mapping import StudentYearMapping
from app.models.teacher import Teacher
from app.models.teacher_class_subject import TeacherClassSubject
from app.utils.enums import EnrollmentStatus, RoleEnum
from sqlalchemy import func, select
from app.services.academic_year import get_active_year

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
    token = extract_bearer_token(request.headers.get("Authorization"))
    if not token:
        # get_current_user already guarantees auth, this is a defensive fallback.
        raise UnauthorizedException(detail="Missing bearer token")

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

    role = user.role if user else current_user.role
    profile_created = False
    enrollment_completed = False
    onboarding_message = None
    active_year_id: Optional[uuid.UUID] = None
    if current_user.school_id is not None:
        try:
            active_year_id = (await get_active_year(current_user.school_id, db)).id
        except Exception:
            active_year_id = None

    if role == RoleEnum.STUDENT:
        student_row = await db.execute(
            select(Student.id).where(Student.user_id == current_user.id)
        )
        student_id = student_row.scalar_one_or_none()
        profile_created = student_id is not None
        if student_id:
            mapping_row = await db.execute(
                select(func.count(StudentYearMapping.id)).where(
                    StudentYearMapping.student_id == student_id,
                    StudentYearMapping.status == EnrollmentStatus.ACTIVE,
                )
            )
            enrollment_completed = (mapping_row.scalar_one() or 0) > 0
        if not profile_created:
            onboarding_message = (
                "Enrollment pending: your student profile is not created yet."
            )
        elif not enrollment_completed:
            onboarding_message = (
                "Enrollment pending: class/section allotment is not completed yet."
            )

    elif role == RoleEnum.TEACHER:
        teacher_row = await db.execute(
            select(Teacher.id).where(Teacher.user_id == current_user.id)
        )
        teacher_id = teacher_row.scalar_one_or_none()
        profile_created = teacher_id is not None
        if teacher_id:
            teacher_filters = [TeacherClassSubject.teacher_id == teacher_id]
            if active_year_id is not None:
                teacher_filters.append(
                    TeacherClassSubject.academic_year_id == active_year_id
                )
            assignment_row = await db.execute(
                select(func.count(TeacherClassSubject.id)).where(*teacher_filters)
            )
            enrollment_completed = (assignment_row.scalar_one() or 0) > 0
        if not profile_created:
            onboarding_message = (
                "Enrollment pending: your teacher profile is not created yet."
            )
        elif not enrollment_completed:
            onboarding_message = (
                "Enrollment pending: teaching assignment is not completed yet."
            )

    elif role == RoleEnum.PARENT:
        parent_row = await db.execute(
            select(Parent.id).where(Parent.user_id == current_user.id)
        )
        parent_id = parent_row.scalar_one_or_none()
        profile_created = parent_id is not None
        if parent_id:
            child_row = await db.execute(
                select(func.count(Student.id)).where(Student.parent_id == parent_id)
            )
            enrollment_completed = (child_row.scalar_one() or 0) > 0
        if not profile_created:
            onboarding_message = (
                "Enrollment pending: your parent profile is not created yet."
            )
        elif not enrollment_completed:
            onboarding_message = (
                "Enrollment pending: child linking is not completed yet."
            )
    else:
        profile_created = True
        enrollment_completed = True

    enrollment_pending = not enrollment_completed

    return CurrentUserSchema(
        id=current_user.id,
        role=role,
        school_id=current_user.school_id,
        parent_id=current_user.parent_id,
        permissions=current_user.permissions,
        full_name=user.full_name if user else current_user.full_name,
        email=user.email if user else current_user.email,
        phone=user.phone if user else current_user.phone,
        status=user.status if user else current_user.status,
        is_active=user.is_active if user else current_user.is_active,
        profile_created=profile_created,
        enrollment_completed=enrollment_completed,
        enrollment_pending=enrollment_pending,
        onboarding_message=onboarding_message,
    )

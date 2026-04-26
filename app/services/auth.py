import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.repositories.user import UserRepository
from app.repositories.otp_store import OtpStoreRepository
from app.repositories.jti_blocklist import JtiBlocklistRepository
from app.core.security import (
    verify_password,
    hash_password,
    hash_otp,
    verify_otp,
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_refresh_token,
    decode_reset_token,
)
from app.core.exceptions import UnauthorizedException, NotFoundException, ValidationException
from app.core.config import settings
from app.models.user import User
from app.utils.enums import RoleEnum, UserStatus
from app.utils.helpers import generate_otp
from app.utils.constants import OTP_EXPIRE_MINUTES, RESET_TOKEN_TYPE


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.otp_repo = OtpStoreRepository(db)
        self.jti_repo = JtiBlocklistRepository(db)

    async def _get_permissions_for_role(self, role: RoleEnum) -> list[str]:
        from app.models.role import Role
        from app.models.permission import Permission
        from app.models.role_permission import RolePermission
        from sqlalchemy import join

        try:
            stmt = (
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(Role, Role.id == RolePermission.role_id)
                .where(Role.name == role.value)
            )
            result = await self.db.execute(stmt)
            return list(result.scalars().all())
        except Exception:
            return []

    async def _get_parent_id_for_user(self, user_id: uuid.UUID) -> Optional[uuid.UUID]:
        try:
            from app.models.parent import Parent
            result = await self.db.execute(
                select(Parent.id).where(Parent.user_id == user_id)
            )
            parent = result.scalar_one_or_none()
            return parent
        except Exception:
            return None

    async def _build_token_payload(self, user: User) -> dict:
        permissions = await self._get_permissions_for_role(user.role)

        payload: dict = {
            "sub": str(user.id),
            "role": user.role.value,
            "school_id": str(user.school_id) if user.school_id else None,
            "permissions": permissions,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "status": user.status.value,
            "is_active": user.is_active,
        }

        if user.role == RoleEnum.PARENT:
            parent_id = await self._get_parent_id_for_user(user.id)
            payload["parent_id"] = str(parent_id) if parent_id else None

        return payload

    async def login(self, email: Optional[str], phone: Optional[str], password: str) -> dict:
        if not email and not phone:
            raise ValidationException("Email or phone is required")

        user = await self.user_repo.get_by_email_or_phone(email, phone)

        if not user:
            raise UnauthorizedException(detail="Invalid credentials")

        if user.status != UserStatus.ACTIVE:
            status_messages = {
                UserStatus.PENDING_APPROVAL: "Your account is pending approval by the administrator.",
                UserStatus.REJECTED: "Your account has been rejected. Please contact the school.",
                UserStatus.ON_HOLD: "Your account is currently on hold. Please contact the school.",
                UserStatus.HOLD: "Your account is currently on hold. Please contact the school.",
                UserStatus.INACTIVE: "Your account has been deactivated.",
                UserStatus.DISABLED: "Your account has been deactivated.",
            }
            msg = status_messages.get(user.status, "Account is not active.")
            raise UnauthorizedException(detail=msg)

        if not user.is_active:
            raise UnauthorizedException(detail="Account is deactivated")

        if not user.hashed_password:
            raise UnauthorizedException(detail="This account does not support password login")

        if not verify_password(password, user.hashed_password):
            raise UnauthorizedException(detail="Invalid credentials")

        payload = await self._build_token_payload(user)

        access_token = create_access_token(payload)
        refresh_token = create_refresh_token({"sub": str(user.id), "school_id": payload["school_id"]})

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def refresh_token(self, refresh_token: str) -> dict:
        payload = decode_refresh_token(refresh_token)

        jti = payload.get("jti")
        if jti:
            is_blocked = await self.jti_repo.is_blocked(jti)
            if is_blocked:
                raise UnauthorizedException(detail="Refresh token has been revoked")

        user_id = uuid.UUID(payload["sub"])
        user = await self.user_repo.get_by_id(user_id)

        if not user or not user.is_active or user.status != UserStatus.ACTIVE:
            raise UnauthorizedException(detail="User not found or deactivated")

        token_payload = await self._build_token_payload(user)
        access_token = create_access_token(token_payload)

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def logout(self, access_token_jti: str, access_token_exp: int, user_id: uuid.UUID, refresh_token: Optional[str] = None) -> None:
        expires_at = datetime.fromtimestamp(access_token_exp, tz=timezone.utc)
        await self.jti_repo.add(access_token_jti, user_id, expires_at)

        if refresh_token:
            try:
                rt_payload = decode_refresh_token(refresh_token)
                rt_jti = rt_payload.get("jti")
                rt_exp = rt_payload.get("exp")
                if rt_jti and rt_exp:
                    rt_expires = datetime.fromtimestamp(rt_exp, tz=timezone.utc)
                    await self.jti_repo.add(rt_jti, user_id, rt_expires)
            except Exception:
                pass

    async def forgot_password(self, email: Optional[str], phone: Optional[str]) -> dict:
        if not email and not phone:
            raise ValidationException("Email or phone is required")

        user = await self.user_repo.get_by_email_or_phone(email, phone)
        if not user:
            return {"message": "If an account exists, an OTP has been sent", "hint": None}

        if not user.is_active or user.status != UserStatus.ACTIVE:
            raise UnauthorizedException(detail="Account is deactivated")

        await self.otp_repo.invalidate_all_for_user(user.id)

        otp_plain = generate_otp(6)
        hashed = hash_otp(otp_plain)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)

        await self.otp_repo.create(user.id, hashed, expires_at)

        return {
            "message": "OTP has been sent to your registered email/phone",
            "hint": otp_plain if settings.DEBUG else None,
        }

    async def verify_otp(self, email: Optional[str], phone: Optional[str], otp_code: str) -> dict:
        if not email and not phone:
            raise ValidationException("Email or phone is required")

        user = await self.user_repo.get_by_email_or_phone(email, phone)
        if not user:
            raise UnauthorizedException(detail="Invalid credentials")

        otp_record = await self.otp_repo.get_latest_valid(user.id)
        if not otp_record:
            raise ValidationException("No valid OTP found. Please request a new one.")

        if not verify_otp(otp_code, otp_record.otp_code):
            raise ValidationException("Invalid OTP code")

        await self.otp_repo.mark_used(otp_record.id)

        reset_payload = {
            "sub": str(user.id),
            "email": user.email,
        }
        reset_token = create_reset_token(reset_payload)

        return {
            "reset_token": reset_token,
            "expires_in": 5 * 60,
            "message": "OTP verified. Use the reset token to set a new password.",
        }

    async def reset_password(self, reset_token: str, new_password: str) -> dict:
        payload = decode_reset_token(reset_token)

        jti = payload.get("jti")
        if jti:
            is_blocked = await self.jti_repo.is_blocked(jti)
            if is_blocked:
                raise UnauthorizedException(detail="Reset token has already been used")

        user_id = uuid.UUID(payload["sub"])
        user = await self.user_repo.get_by_id(user_id)

        if not user or not user.is_active or user.status != UserStatus.ACTIVE:
            raise UnauthorizedException(detail="User not found or deactivated")

        new_hashed = hash_password(new_password)
        await self.user_repo.update_password(user_id, new_hashed)

        if jti:
            exp = payload.get("exp", 0)
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
            await self.jti_repo.add(jti, user_id, expires_at)

        return {"message": "Password has been reset successfully. Please log in with your new password."}

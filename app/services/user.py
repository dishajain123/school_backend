import uuid
import math
from typing import Optional
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate, UserMeUpdate
from app.models.user import User
from app.core.security import hash_password
from app.core.exceptions import (
    NotFoundException,
    ConflictException,
    ForbiddenException,
    ValidationException,
)
from app.core.dependencies import CurrentUser
from app.integrations.minio_client import upload_file, generate_presigned_url
from app.utils.enums import RoleEnum
from app.utils.constants import (
    ALLOWED_IMAGE_TYPES,
    MAX_FILE_SIZE_BYTES,
)
from app.utils.validators import validate_file_size, validate_mime_type
from app.core.config import settings


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = UserRepository(db)

    def _build_photo_key(self, user_id: uuid.UUID, filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
        return f"users/{user_id}/profile.{ext}"

    async def _enrich_with_photo_url(self, user: User) -> dict:
        data = {
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "school_id": user.school_id,
            "is_active": user.is_active,
            "profile_photo_key": user.profile_photo_key,
            "profile_photo_url": None,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }
        if user.profile_photo_key:
            try:
                data["profile_photo_url"] = generate_presigned_url(
                    settings.MINIO_BUCKET_PROFILES,
                    user.profile_photo_key,
                )
            except Exception:
                pass
        return data

    async def create_user(
        self,
        data: UserCreate,
        school_id: uuid.UUID,
    ) -> User:
        if not data.email and not data.phone:
            raise ValidationException("Either email or phone is required")

        if data.email:
            existing = await self.repo.get_by_email(str(data.email))
            if existing:
                raise ConflictException(f"Email '{data.email}' is already in use")

        if data.phone:
            existing = await self.repo.get_by_phone(data.phone)
            if existing:
                raise ConflictException(f"Phone '{data.phone}' is already in use")

        user = await self.repo.create({
            "email": str(data.email).lower().strip() if data.email else None,
            "phone": data.phone,
            "hashed_password": hash_password(data.password),
            "role": data.role,
            "school_id": school_id,
            "is_active": data.is_active,
        })
        return user

    async def get_user(self, user_id: uuid.UUID, school_id: uuid.UUID) -> User:
        user = await self.repo.get_by_id(user_id)
        if not user or user.school_id != school_id:
            raise NotFoundException("User")
        return user

    async def list_users(
        self,
        school_id: uuid.UUID,
        role: Optional[RoleEnum] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int, int]:
        users, total = await self.repo.list_by_school(
            school_id=school_id,
            role=role,
            is_active=is_active,
            page=page,
            page_size=page_size,
        )
        enriched = []
        for u in users:
            enriched.append(await self._enrich_with_photo_url(u))
        total_pages = math.ceil(total / page_size) if total > 0 else 1
        return enriched, total, total_pages

    async def update_user(
        self,
        user_id: uuid.UUID,
        school_id: uuid.UUID,
        data: UserUpdate,
    ) -> User:
        user = await self.get_user(user_id, school_id)

        update_data = data.model_dump(exclude_none=True)

        if "email" in update_data:
            new_email = str(update_data["email"]).lower().strip()
            if new_email != user.email:
                existing = await self.repo.get_by_email(new_email)
                if existing:
                    raise ConflictException(f"Email '{new_email}' is already in use")
            update_data["email"] = new_email

        if "phone" in update_data and update_data["phone"] != user.phone:
            existing = await self.repo.get_by_phone(update_data["phone"])
            if existing:
                raise ConflictException(f"Phone '{update_data['phone']}' is already in use")

        return await self.repo.update(user, update_data)

    async def deactivate_user(self, user_id: uuid.UUID, school_id: uuid.UUID) -> User:
        user = await self.get_user(user_id, school_id)
        if not user.is_active:
            raise ConflictException("User is already deactivated")
        return await self.repo.deactivate(user)

    async def upload_profile_photo(
        self,
        user_id: uuid.UUID,
        school_id: uuid.UUID,
        file: UploadFile,
        current_user: CurrentUser,
    ) -> dict:
        is_own_profile = current_user.id == user_id
        is_manager = current_user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)

        if not is_own_profile and not is_manager:
            raise ForbiddenException("You can only upload your own profile photo")

        user = await self.get_user(user_id, school_id)

        content_type = file.content_type or "application/octet-stream"
        validate_mime_type(content_type, ALLOWED_IMAGE_TYPES)

        file_bytes = await file.read()
        validate_file_size(len(file_bytes), MAX_FILE_SIZE_BYTES)

        photo_key = self._build_photo_key(user_id, file.filename or "profile.jpg")
        upload_file(
            bucket=settings.MINIO_BUCKET_PROFILES,
            key=photo_key,
            file_bytes=file_bytes,
            content_type=content_type,
        )

        updated_user = await self.repo.update_photo(user_id, photo_key)
        photo_url = generate_presigned_url(settings.MINIO_BUCKET_PROFILES, photo_key)

        return {
            "profile_photo_key": photo_key,
            "profile_photo_url": photo_url,
            "message": "Profile photo uploaded successfully",
        }

    async def get_me(self, current_user: CurrentUser) -> dict:
        user = await self.repo.get_by_id(current_user.id)
        if not user:
            raise NotFoundException("User")
        return await self._enrich_with_photo_url(user)

    async def update_me(
        self,
        current_user: CurrentUser,
        data: UserMeUpdate,
    ) -> User:
        user = await self.repo.get_by_id(current_user.id)
        if not user:
            raise NotFoundException("User")

        update_data = data.model_dump(exclude_none=True)

        if "phone" in update_data and update_data["phone"] != user.phone:
            existing = await self.repo.get_by_phone(update_data["phone"])
            if existing:
                raise ConflictException(f"Phone '{update_data['phone']}' is already in use")

        return await self.repo.update(user, update_data)
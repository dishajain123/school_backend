import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.parent import ParentRepository
from app.repositories.user import UserRepository
from app.schemas.parent import ParentCreate, ParentUpdate
from app.models.parent import Parent
from app.models.student import Student
from app.core.security import hash_password
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ConflictException,
)
from app.core.dependencies import CurrentUser
from app.utils.enums import RoleEnum


class ParentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.parent_repo = ParentRepository(db)
        self.user_repo = UserRepository(db)

    async def create_parent(
        self,
        payload: ParentCreate,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Parent:
        # Guard: email uniqueness
        existing_email = await self.user_repo.get_by_email(payload.user.email)
        if existing_email:
            raise ConflictException(detail="A user with this email already exists")

        # Guard: phone uniqueness
        existing_phone = await self.user_repo.get_by_phone(payload.user.phone)
        if existing_phone:
            raise ConflictException(detail="A user with this phone number already exists")

        # 1. Create users row (role=PARENT)
        user = await self.user_repo.create(
            {
                "email": payload.user.email.lower().strip(),
                "phone": payload.user.phone,
                "hashed_password": hash_password(payload.user.password),
                "role": RoleEnum.PARENT,
                "school_id": school_id,
                "is_active": True,
            }
        )

        # 2. Create parents row linked to that user
        parent = await self.parent_repo.create(
            {
                "user_id": user.id,
                "school_id": school_id,
                "occupation": payload.occupation,
                "relation": payload.relation,
            }
        )

        await self.db.commit()
        await self.db.refresh(parent)

        # Reload with user eager-loaded
        return await self.parent_repo.get_by_id(parent.id, school_id)  # type: ignore[return-value]

    async def get_parent(
        self,
        parent_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Parent:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        parent = await self.parent_repo.get_by_id(parent_id, school_id)
        if not parent:
            raise NotFoundException(detail="Parent not found")

        # A PARENT role user may only view their own profile
        if current_user.role == RoleEnum.PARENT:
            if current_user.parent_id != parent.id:
                from app.core.exceptions import ForbiddenException
                raise ForbiddenException(detail="Access denied")

        return parent

    async def list_parents(
        self,
        school_id: uuid.UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[Parent], int]:
        return await self.parent_repo.list_by_school(school_id, page, page_size)

    async def update_parent(
        self,
        parent_id: uuid.UUID,
        payload: ParentUpdate,
        current_user: CurrentUser,
    ) -> Parent:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        parent = await self.parent_repo.get_by_id(parent_id, school_id)
        if not parent:
            raise NotFoundException(detail="Parent not found")

        update_data = payload.model_dump(exclude_unset=True)
        updated = await self.parent_repo.update(parent, update_data)
        await self.db.commit()
        await self.db.refresh(updated)
        return await self.parent_repo.get_by_id(parent_id, school_id)  # type: ignore[return-value]

    async def get_children(
        self,
        parent_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> tuple[uuid.UUID, list[Student]]:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        parent = await self.parent_repo.get_by_id(parent_id, school_id)
        if not parent:
            raise NotFoundException(detail="Parent not found")

        # PARENT role may only see their own children
        if current_user.role == RoleEnum.PARENT:
            if current_user.parent_id != parent.id:
                from app.core.exceptions import ForbiddenException
                raise ForbiddenException(detail="Access denied")

        children = await self.parent_repo.get_children(parent_id, school_id)
        return parent.id, children

    async def get_my_children(
        self,
        current_user: CurrentUser,
    ) -> tuple[uuid.UUID, list[Student]]:
        if current_user.role != RoleEnum.PARENT:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException(detail="Only parents can access this endpoint")

        if not current_user.parent_id:
            raise NotFoundException(detail="Parent profile not found for this user")

        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        children = await self.parent_repo.get_children(current_user.parent_id, school_id)
        return current_user.parent_id, children
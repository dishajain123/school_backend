import uuid
from typing import Optional
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.utils.enums import RoleEnum


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> User:
        user = User(**data)
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.phone == phone)
        )
        return result.scalar_one_or_none()

    async def get_by_email_or_phone(
        self,
        email: Optional[str],
        phone: Optional[str],
    ) -> Optional[User]:
        if email:
            user = await self.get_by_email(email)
            if user:
                return user
        if phone:
            user = await self.get_by_phone(phone)
            if user:
                return user
        return None

    async def list_by_school(
        self,
        school_id: uuid.UUID,
        role: Optional[RoleEnum] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[User], int]:
        query = select(User).where(User.school_id == school_id)
        count_query = select(func.count(User.id)).where(User.school_id == school_id)

        if role is not None:
            query = query.where(User.role == role)
            count_query = count_query.where(User.role == role)

        if is_active is not None:
            query = query.where(User.is_active == is_active)
            count_query = count_query.where(User.is_active == is_active)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        offset = (page - 1) * page_size
        query = query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    async def update(self, user: User, data: dict) -> User:
        for key, value in data.items():
            setattr(user, key, value)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update_password(self, user_id: uuid.UUID, hashed_password: str) -> None:
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(hashed_password=hashed_password)
        )
        await self.db.flush()

    async def update_photo(self, user_id: uuid.UUID, photo_key: str) -> Optional[User]:
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(profile_photo_key=photo_key)
        )
        await self.db.flush()
        return await self.get_by_id(user_id)

    async def deactivate(self, user: User) -> User:
        user.is_active = False
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def get_by_school_and_role(
        self,
        school_id: uuid.UUID,
        role: Optional[RoleEnum] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[User], int]:
        return await self.list_by_school(
            school_id=school_id,
            role=role,
            page=page,
            page_size=page_size,
        )
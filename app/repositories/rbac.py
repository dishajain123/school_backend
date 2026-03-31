import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.role import Role
from app.models.permission import Permission
from app.models.role_permission import RolePermission


class RbacRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_role_by_name(self, name: str) -> Optional[Role]:
        result = await self.db.execute(
            select(Role).where(Role.name == name)
        )
        return result.scalar_one_or_none()

    async def get_permission_by_code(self, code: str) -> Optional[Permission]:
        result = await self.db.execute(
            select(Permission).where(Permission.code == code)
        )
        return result.scalar_one_or_none()

    async def upsert_role(self, name: str, description: str) -> Role:
        existing = await self.get_role_by_name(name)
        if existing:
            return existing
        role = Role(name=name, description=description)
        self.db.add(role)
        await self.db.flush()
        await self.db.refresh(role)
        return role

    async def upsert_permission(self, code: str, description: str) -> Permission:
        existing = await self.get_permission_by_code(code)
        if existing:
            return existing
        perm = Permission(code=code, description=description)
        self.db.add(perm)
        await self.db.flush()
        await self.db.refresh(perm)
        return perm

    async def assign_permission_to_role(self, role_id: uuid.UUID, permission_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            )
        )
        if result.scalar_one_or_none():
            return
        rp = RolePermission(role_id=role_id, permission_id=permission_id)
        self.db.add(rp)
        await self.db.flush()

    async def get_permissions_for_role(self, role_name: str) -> list[str]:
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .where(Role.name == role_name)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_roles(self) -> list[Role]:
        result = await self.db.execute(select(Role).order_by(Role.name))
        return list(result.scalars().all())

    async def get_all_permissions(self) -> list[Permission]:
        result = await self.db.execute(select(Permission).order_by(Permission.code))
        return list(result.scalars().all())
import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.teacher_leave import TeacherLeave
from app.models.leave_balance import LeaveBalance


class LeaveRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_leave(self, data: dict) -> TeacherLeave:
        obj = TeacherLeave(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_leave_by_id(
        self, leave_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[TeacherLeave]:
        result = await self.db.execute(
            select(TeacherLeave).where(
                and_(
                    TeacherLeave.id == leave_id,
                    TeacherLeave.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_leaves(
        self,
        school_id: uuid.UUID,
        teacher_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> list[TeacherLeave]:
        stmt = select(TeacherLeave).where(TeacherLeave.school_id == school_id)
        if teacher_id:
            stmt = stmt.where(TeacherLeave.teacher_id == teacher_id)
        if status:
            stmt = stmt.where(TeacherLeave.status == status)
        if academic_year_id:
            stmt = stmt.where(TeacherLeave.academic_year_id == academic_year_id)
        stmt = stmt.order_by(TeacherLeave.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_leave(self, leave: TeacherLeave, data: dict) -> TeacherLeave:
        for key, value in data.items():
            setattr(leave, key, value)
        await self.db.flush()
        await self.db.refresh(leave)
        return leave

    # Leave Balance
    async def get_balance(
        self,
        teacher_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        leave_type,
    ) -> Optional[LeaveBalance]:
        result = await self.db.execute(
            select(LeaveBalance).where(
                and_(
                    LeaveBalance.teacher_id == teacher_id,
                    LeaveBalance.academic_year_id == academic_year_id,
                    LeaveBalance.leave_type == leave_type,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_balances(
        self, teacher_id: uuid.UUID, academic_year_id: uuid.UUID
    ) -> list[LeaveBalance]:
        result = await self.db.execute(
            select(LeaveBalance).where(
                and_(
                    LeaveBalance.teacher_id == teacher_id,
                    LeaveBalance.academic_year_id == academic_year_id,
                )
            )
        )
        return list(result.scalars().all())

    async def update_balance(self, balance: LeaveBalance, data: dict) -> LeaveBalance:
        for key, value in data.items():
            setattr(balance, key, value)
        await self.db.flush()
        await self.db.refresh(balance)
        return balance

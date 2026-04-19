import uuid
from datetime import date
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException, ConflictException
from app.repositories.leave import LeaveRepository
from app.repositories.teacher import TeacherRepository
from app.repositories.notification import NotificationRepository
from app.schemas.leave import (
    LeaveApplyRequest,
    LeaveBalanceAllocationRequest,
    LeaveDecisionRequest,
    LeaveResponse,
    LeaveListResponse,
    LeaveBalanceResponse,
)
from app.services.academic_year import get_active_year
from app.services.assignment import _get_teacher_id
from app.utils.enums import RoleEnum, LeaveStatus, NotificationType, NotificationPriority


async def _notify_principal(
    school_id: uuid.UUID,
    leave_id: uuid.UUID,
    title: str,
    body: str,
) -> None:
    """Opens its own DB session — never reuses the request session."""
    from app.db.session import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User.id).where(
                and_(
                    User.school_id == school_id,
                    User.role == RoleEnum.PRINCIPAL,
                )
            )
        )
        user_ids = [row[0] for row in result.all()]
        repo = NotificationRepository(db)
        for user_id in user_ids:
            await repo.create(
                {
                    "user_id": user_id,
                    "title": title,
                    "body": body,
                    "type": NotificationType.LEAVE,
                    "priority": NotificationPriority.MEDIUM,
                    "reference_id": leave_id,
                }
            )
        await db.commit()


async def _notify_teacher(
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    title: str,
    body: str,
) -> None:
    """Opens its own DB session — never reuses the request session."""
    from app.db.session import AsyncSessionLocal
    from app.models.teacher import Teacher

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Teacher.user_id).where(
                and_(
                    Teacher.id == teacher_id,
                    Teacher.school_id == school_id,
                )
            )
        )
        user_id = result.scalar_one_or_none()
        if not user_id:
            return
        repo = NotificationRepository(db)
        await repo.create(
            {
                "user_id": user_id,
                "title": title,
                "body": body,
                "type": NotificationType.LEAVE,
                "priority": NotificationPriority.MEDIUM,
                "reference_id": teacher_id,
            }
        )
        await db.commit()


class LeaveService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = LeaveRepository(db)
        self.teacher_repo = TeacherRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def _approved_days(
        self,
        teacher_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        leave_type,
    ) -> float:
        approved = await self.repo.list_approved_leaves(
            teacher_id=teacher_id,
            academic_year_id=academic_year_id,
            leave_type=leave_type,
        )
        days = 0.0
        for leave in approved:
            days += float((leave.to_date - leave.from_date).days + 1)
        return days

    async def _sync_used_days(
        self,
        teacher_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        leave_type,
    ) -> None:
        balance = await self.repo.get_balance(
            teacher_id=teacher_id,
            academic_year_id=academic_year_id,
            leave_type=leave_type,
        )
        if not balance:
            return
        used = await self._approved_days(
            teacher_id=teacher_id,
            academic_year_id=academic_year_id,
            leave_type=leave_type,
        )
        await self.repo.update_balance(balance, {"used_days": used})

    async def apply_leave(
        self,
        body: LeaveApplyRequest,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> LeaveResponse:
        school_id = self._ensure_school(current_user)
        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)

        days_requested = (body.to_date - body.from_date).days + 1
        if days_requested <= 0:
            raise ValidationException("Invalid leave dates")

        balance = await self.repo.get_balance(
            teacher_id=teacher_id,
            academic_year_id=academic_year_id,
            leave_type=body.leave_type,
        )
        if not balance:
            raise ValidationException("Leave balance not configured")

        used_days = await self._approved_days(
            teacher_id=teacher_id,
            academic_year_id=academic_year_id,
            leave_type=body.leave_type,
        )
        remaining = float(balance.total_days) - used_days
        if remaining < days_requested:
            raise ValidationException("Insufficient leave balance")

        leave = await self.repo.create_leave(
            {
                "teacher_id": teacher_id,
                "leave_type": body.leave_type,
                "from_date": body.from_date,
                "to_date": body.to_date,
                "reason": body.reason,
                "status": LeaveStatus.PENDING,
                "approved_by": None,
                "remarks": None,
                "academic_year_id": academic_year_id,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(leave)

        background_tasks.add_task(
            _notify_principal,
            school_id,
            leave.id,
            "New Leave Request",
            f"Leave request from teacher {teacher_id}",
        )

        return LeaveResponse.model_validate(leave)

    async def decide_leave(
        self,
        leave_id: uuid.UUID,
        body: LeaveDecisionRequest,
        current_user: CurrentUser,
    ) -> LeaveResponse:
        school_id = self._ensure_school(current_user)
        leave = await self.repo.get_leave_by_id(leave_id, school_id)
        if not leave:
            raise NotFoundException("Leave")

        if leave.status != LeaveStatus.PENDING:
            raise ConflictException("Leave decision already made")

        update_data = {
            "status": body.status,
            "remarks": body.remarks,
            "approved_by": current_user.id,
        }

        if body.status == LeaveStatus.APPROVED:
            balance = await self.repo.get_balance(
                teacher_id=leave.teacher_id,
                academic_year_id=leave.academic_year_id,
                leave_type=leave.leave_type,
            )
            if not balance:
                raise ValidationException("Leave balance not configured")

            days_requested = (leave.to_date - leave.from_date).days + 1
            used_days = await self._approved_days(
                teacher_id=leave.teacher_id,
                academic_year_id=leave.academic_year_id,
                leave_type=leave.leave_type,
            )
            remaining = float(balance.total_days) - used_days
            if remaining < days_requested:
                raise ValidationException("Insufficient leave balance")

        updated = await self.repo.update_leave(leave, update_data)
        await self._sync_used_days(
            teacher_id=updated.teacher_id,
            academic_year_id=updated.academic_year_id,
            leave_type=updated.leave_type,
        )
        await self.db.commit()
        await self.db.refresh(updated)

        # Notify teacher synchronously (small payload, no background task needed)
        await _notify_teacher(
            school_id,
            updated.teacher_id,
            "Leave Decision",
            f"Your leave request is {updated.status.value}",
        )

        return LeaveResponse.model_validate(updated)

    async def list_leaves(
        self,
        current_user: CurrentUser,
        status: Optional[LeaveStatus],
        academic_year_id: Optional[uuid.UUID],
    ) -> LeaveListResponse:
        school_id = self._ensure_school(current_user)
        teacher_id: Optional[uuid.UUID] = None

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)

        leaves = await self.repo.list_leaves(
            school_id=school_id,
            teacher_id=teacher_id,
            status=status.value if status else None,
            academic_year_id=academic_year_id,
        )
        return LeaveListResponse(
            items=[LeaveResponse.model_validate(l) for l in leaves],
            total=len(leaves),
        )

    async def get_balance(
        self,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID],
    ) -> list[LeaveBalanceResponse]:
        school_id = self._ensure_school(current_user)
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
        balances = await self.repo.list_balances(teacher_id, academic_year_id)

        results = []
        for b in balances:
            used_days = await self._approved_days(
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
                leave_type=b.leave_type,
            )
            remaining = float(b.total_days) - used_days
            results.append(
                LeaveBalanceResponse(
                    leave_type=b.leave_type,
                    total_days=float(b.total_days),
                    used_days=used_days,
                    remaining_days=max(0.0, remaining),
                )
            )
        return results

    async def get_teacher_balance(
        self,
        teacher_id: uuid.UUID,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID],
    ) -> list[LeaveBalanceResponse]:
        school_id = self._ensure_school(current_user)
        teacher = await self.teacher_repo.get_by_id(teacher_id, school_id)
        if not teacher:
            raise NotFoundException("Teacher")

        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        balances = await self.repo.list_balances(teacher_id, academic_year_id)
        results = []
        for b in balances:
            used_days = await self._approved_days(
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
                leave_type=b.leave_type,
            )
            results.append(
                LeaveBalanceResponse(
                    leave_type=b.leave_type,
                    total_days=float(b.total_days),
                    used_days=used_days,
                    remaining_days=max(0.0, float(b.total_days) - used_days),
                )
            )
        return results

    async def set_teacher_balance(
        self,
        teacher_id: uuid.UUID,
        body: LeaveBalanceAllocationRequest,
        current_user: CurrentUser,
    ) -> list[LeaveBalanceResponse]:
        school_id = self._ensure_school(current_user)
        teacher = await self.teacher_repo.get_by_id(teacher_id, school_id)
        if not teacher:
            raise NotFoundException("Teacher")

        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        for item in body.allocations:
            existing = await self.repo.get_balance(
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
                leave_type=item.leave_type,
            )

            if existing:
                used_days = await self._approved_days(
                    teacher_id=teacher_id,
                    academic_year_id=academic_year_id,
                    leave_type=item.leave_type,
                )
                if item.total_days < used_days:
                    raise ValidationException(
                        f"Allocated days for {item.leave_type.value} cannot be lower than used days ({used_days})"
                    )
                await self.repo.update_balance(
                    existing,
                    {"total_days": float(item.total_days)},
                )
                continue

            await self.repo.create_balance(
                {
                    "teacher_id": teacher_id,
                    "academic_year_id": academic_year_id,
                    "leave_type": item.leave_type,
                    "total_days": float(item.total_days),
                    "used_days": 0.0,
                    "school_id": school_id,
                }
            )

        for item in body.allocations:
            await self._sync_used_days(
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
                leave_type=item.leave_type,
            )
        await self.db.commit()
        balances = await self.repo.list_balances(teacher_id, academic_year_id)
        results = []
        for b in balances:
            used_days = await self._approved_days(
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
                leave_type=b.leave_type,
            )
            results.append(
                LeaveBalanceResponse(
                    leave_type=b.leave_type,
                    total_days=float(b.total_days),
                    used_days=used_days,
                    remaining_days=max(0.0, float(b.total_days) - used_days),
                )
            )
        return results

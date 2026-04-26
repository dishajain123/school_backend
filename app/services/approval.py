import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.models.user import User
from app.models.user_approval_audit import UserApprovalAudit
from app.schemas.approval import ApprovalDecisionRequest
from app.services.registration import RegistrationService
from app.utils.enums import ApprovalAction, RegistrationSource, RoleEnum, UserStatus


class ApprovalService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.registration_service = RegistrationService(db)

    @staticmethod
    def _can_decide(user: CurrentUser) -> bool:
        return user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)

    async def _get_user_in_scope(self, user_id: uuid.UUID, current_user: CurrentUser) -> User:
        stmt = select(User).where(User.id == user_id)
        if current_user.role != RoleEnum.SUPERADMIN:
            stmt = stmt.where(User.school_id == current_user.school_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User")
        return user

    async def list_queue(
        self,
        current_user: CurrentUser,
        page: int,
        page_size: int,
        status: Optional[UserStatus] = None,
        role: Optional[RoleEnum] = None,
        source: Optional[RegistrationSource] = None,
        q: Optional[str] = None,
    ) -> tuple[list[User], int, int]:
        filters = []
        if current_user.role != RoleEnum.SUPERADMIN:
            filters.append(User.school_id == current_user.school_id)

        if status is not None:
            filters.append(User.status == status)
        else:
            filters.append(User.status.in_([UserStatus.PENDING_APPROVAL, UserStatus.REJECTED]))

        if role is not None:
            filters.append(User.role == role)

        if source is not None:
            filters.append(User.registration_source == source)

        if q:
            qv = f"%{q.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(User.full_name, "")).like(qv),
                    func.lower(func.coalesce(User.email, "")).like(qv),
                    func.lower(func.coalesce(User.phone, "")).like(qv),
                )
            )

        base = select(User)
        count_base = select(func.count(User.id))
        if filters:
            base = base.where(and_(*filters))
            count_base = count_base.where(and_(*filters))

        total = (await self.db.execute(count_base)).scalar_one()
        rows = await self.db.execute(
            base.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        items = list(rows.scalars().all())
        total_pages = math.ceil(total / page_size) if total else 1
        return items, total, total_pages

    async def get_detail(
        self,
        user_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> tuple[User, list[dict], list[dict]]:
        user = await self._get_user_in_scope(user_id, current_user)
        issues, duplicates = await self.registration_service.validate_user_for_approval(user)
        return user, issues, duplicates

    async def decide(
        self,
        user_id: uuid.UUID,
        data: ApprovalDecisionRequest,
        current_user: CurrentUser,
    ) -> tuple[User, list[dict], list[dict], datetime]:
        if not self._can_decide(current_user):
            raise ForbiddenException("Only Principal or Superadmin can approve/reject requests")

        user = await self._get_user_in_scope(user_id, current_user)
        now = datetime.now(timezone.utc)
        from_status = user.status

        issues, duplicates = await self.registration_service.validate_user_for_approval(user)
        blocking_findings = bool(issues or duplicates)
        if (
            data.action == ApprovalAction.APPROVE
            and blocking_findings
            and not (data.override_validation and current_user.role == RoleEnum.SUPERADMIN)
        ):
            raise ValidationException(
                "Approval blocked due to validation issues/duplicates. Superadmin may override."
            )

        if data.override_validation and current_user.role != RoleEnum.SUPERADMIN:
            raise ForbiddenException("Only Superadmin can use override_validation")

        if data.action == ApprovalAction.APPROVE:
            user.status = UserStatus.ACTIVE
            user.is_active = True
            user.rejection_reason = None
            user.hold_reason = None
            user.approved_by_id = current_user.id
            user.approved_at = now
        elif data.action == ApprovalAction.REJECT:
            if not data.note:
                raise ValidationException("Rejection reason is required")
            user.status = UserStatus.REJECTED
            user.is_active = False
            user.rejection_reason = data.note
            user.hold_reason = None
            user.approved_by_id = current_user.id
            user.approved_at = now
        elif data.action == ApprovalAction.HOLD:
            user.status = UserStatus.PENDING_APPROVAL
            user.is_active = False
            user.hold_reason = data.note or "On hold pending additional verification"
            user.rejection_reason = None
            user.approved_by_id = current_user.id
            user.approved_at = now
        else:
            raise ValidationException("Unsupported approval action")

        audit = UserApprovalAudit(
            user_id=user.id,
            acted_by_id=current_user.id,
            action=data.action,
            from_status=from_status,
            to_status=user.status,
            note=data.note,
            validation_issues=issues or None,
            duplicate_matches=duplicates or None,
            acted_at=now,
        )
        self.db.add(audit)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(user)

        return user, issues, duplicates, now

    async def list_audit(
        self,
        current_user: CurrentUser,
        page: int,
        page_size: int,
        user_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[UserApprovalAudit], int, int]:
        filters = []
        if user_id is not None:
            filters.append(UserApprovalAudit.user_id == user_id)

        stmt = select(UserApprovalAudit)
        count_stmt = select(func.count(UserApprovalAudit.id))

        if current_user.role != RoleEnum.SUPERADMIN:
            # Scope audits by joining user school.
            stmt = stmt.join(User, User.id == UserApprovalAudit.user_id)
            count_stmt = count_stmt.join(User, User.id == UserApprovalAudit.user_id)
            filters.append(User.school_id == current_user.school_id)

        if filters:
            stmt = stmt.where(and_(*filters))
            count_stmt = count_stmt.where(and_(*filters))

        total = (await self.db.execute(count_stmt)).scalar_one()
        rows = await self.db.execute(
            stmt.order_by(UserApprovalAudit.acted_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(rows.scalars().all())
        total_pages = math.ceil(total / page_size) if total else 1
        return items, total, total_pages

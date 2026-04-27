# app/api/v1/endpoints/audit_logs.py
"""
Phase 14 — Audit & Traceability.
System-wide audit trail endpoint.

The AuditLog table records every critical action: approvals, enrollments,
promotions, fee events — written by AuditLogService.log() across services.
This endpoint exposes the logs as a filterable, paginated read-only API.

Permission:
  SUPERADMIN : full cross-school access
  PRINCIPAL  : school-scoped access
"""
import uuid
import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.core.exceptions import ForbiddenException
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogResponse, AuditLogListResponse
from app.utils.enums import RoleEnum, AuditAction

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: Optional[AuditAction] = Query(None, description="Filter by action type"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type (e.g. StudentYearMapping, User)"),
    actor_id: Optional[uuid.UUID] = Query(None, description="Filter by actor user ID"),
    target_user_id: Optional[uuid.UUID] = Query(None, description="Filter by target user ID"),
    date_from: Optional[date] = Query(None, description="Filter from date (inclusive)"),
    date_to: Optional[date] = Query(None, description="Filter to date (inclusive)"),
    q: Optional[str] = Query(None, description="Search in description"),
    current_user: CurrentUser = Depends(
        require_roles(RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Phase 14: List all system-wide audit log entries.

    Includes actions from:
    - User approvals / rejections / holds
    - Student enrollment, exits, promotions
    - Teacher assignments
    - Fee structure changes
    - Document verifications
    - Any other action logged via AuditLogService.log()

    SUPERADMIN sees all schools. PRINCIPAL sees their school only.
    Records are immutable — never updated or deleted.
    """
    filters = []

    # School scope
    if current_user.role != RoleEnum.SUPERADMIN:
        if not current_user.school_id:
            raise ForbiddenException("School context required")
        filters.append(AuditLog.school_id == current_user.school_id)

    if action is not None:
        filters.append(AuditLog.action == action)

    if entity_type is not None and entity_type.strip():
        filters.append(AuditLog.entity_type == entity_type.strip())

    if actor_id is not None:
        filters.append(AuditLog.actor_id == actor_id)

    if target_user_id is not None:
        filters.append(AuditLog.target_user_id == target_user_id)

    if date_from is not None:
        filters.append(AuditLog.occurred_at >= date_from)

    if date_to is not None:
        import datetime as dt
        end = dt.datetime.combine(date_to, dt.time.max)
        filters.append(AuditLog.occurred_at <= end)

    if q is not None and q.strip():
        qv = f"%{q.strip().lower()}%"
        filters.append(
            func.lower(AuditLog.description).like(qv)
        )

    base = select(AuditLog)
    count_base = select(func.count(AuditLog.id))
    if filters:
        base = base.where(and_(*filters))
        count_base = count_base.where(and_(*filters))

    total = (await db.execute(count_base)).scalar_one()
    rows = await db.execute(
        base.order_by(AuditLog.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = list(rows.scalars().all())
    total_pages = math.ceil(total / page_size) if total else 1

    # Hydrate actor names in one query
    actor_ids = {log.actor_id for log in logs if log.actor_id}
    actor_names: dict[uuid.UUID, str] = {}
    if actor_ids:
        user_rows = await db.execute(
            select(User.id, User.full_name).where(User.id.in_(actor_ids))
        )
        for uid, name in user_rows.all():
            actor_names[uid] = name or ""

    items = []
    for log in logs:
        resp = AuditLogResponse(
            id=log.id,
            school_id=log.school_id,
            actor_id=log.actor_id,
            actor_name=actor_names.get(log.actor_id) if log.actor_id else None,
            target_user_id=log.target_user_id,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            description=log.description,
            before_state=log.before_state,
            after_state=log.after_state,
            ip_address=log.ip_address,
            occurred_at=log.occurred_at,
        )
        items.append(resp)

    return AuditLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/actions", response_model=list[str])
async def list_audit_actions(
    current_user: CurrentUser = Depends(
        require_roles(RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)
    ),
):
    """Return all possible AuditAction enum values for filter dropdowns."""
    return [a.value for a in AuditAction]


@router.get("/entity-types", response_model=list[str])
async def list_entity_types(
    current_user: CurrentUser = Depends(
        require_roles(RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Return distinct entity_type values present in the audit log."""
    scope_filter = []
    if current_user.role != RoleEnum.SUPERADMIN and current_user.school_id:
        scope_filter = [AuditLog.school_id == current_user.school_id]

    stmt = (
        select(AuditLog.entity_type)
        .distinct()
        .order_by(AuditLog.entity_type)
    )
    if scope_filter:
        stmt = stmt.where(and_(*scope_filter))

    rows = await db.execute(stmt)
    return [r[0] for r in rows.all() if r[0]]
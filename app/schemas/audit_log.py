# app/schemas/audit_log.py
"""
Phase 14 — Audit & Traceability.
Pydantic schemas for the system-wide AuditLog table.
The AuditLog model is already written (app/models/audit_log.py) and
AuditLogService.log() is already called from enrollment, promotion, and approval
services. This file adds the READ schemas so the logs can be exposed via API.
"""
import uuid
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel

from app.utils.enums import AuditAction


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    school_id: Optional[uuid.UUID] = None
    actor_id: Optional[uuid.UUID] = None
    actor_name: Optional[str] = None        # hydrated by service from users table
    target_user_id: Optional[uuid.UUID] = None
    action: AuditAction
    entity_type: str
    entity_id: Optional[str] = None
    description: str
    before_state: Optional[Any] = None
    after_state: Optional[Any] = None
    ip_address: Optional[str] = None
    occurred_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
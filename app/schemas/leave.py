import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.utils.enums import LeaveType, LeaveStatus


class LeaveApplyRequest(BaseModel):
    leave_type: LeaveType
    from_date: date
    to_date: date
    reason: Optional[str] = None
    academic_year_id: Optional[uuid.UUID] = None

    @field_validator("to_date")
    @classmethod
    def validate_dates(cls, v: date, values) -> date:
        from_date = values.data.get("from_date")
        if from_date and v < from_date:
            raise ValueError("to_date must be on or after from_date")
        return v


class LeaveDecisionRequest(BaseModel):
    status: LeaveStatus
    remarks: Optional[str] = None


class LeaveResponse(BaseModel):
    id: uuid.UUID
    teacher_id: uuid.UUID
    leave_type: LeaveType
    from_date: date
    to_date: date
    reason: Optional[str] = None
    status: LeaveStatus
    approved_by: Optional[uuid.UUID] = None
    remarks: Optional[str] = None
    academic_year_id: uuid.UUID
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaveListResponse(BaseModel):
    items: list[LeaveResponse]
    total: int


class LeaveBalanceResponse(BaseModel):
    leave_type: LeaveType
    total_days: float
    used_days: float
    remaining_days: float


class LeaveBalanceAllocationItem(BaseModel):
    leave_type: LeaveType
    total_days: float = Field(ge=0)


class LeaveBalanceAllocationRequest(BaseModel):
    allocations: list[LeaveBalanceAllocationItem] = Field(min_length=1)
    academic_year_id: Optional[uuid.UUID] = None

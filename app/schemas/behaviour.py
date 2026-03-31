import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.utils.enums import IncidentType, IncidentSeverity


class BehaviourCreate(BaseModel):
    student_id: uuid.UUID
    incident_type: IncidentType
    description: str
    severity: IncidentSeverity
    incident_date: Optional[date] = None
    academic_year_id: Optional[uuid.UUID] = None

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description cannot be empty")
        return v


class BehaviourResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    teacher_id: uuid.UUID
    incident_type: IncidentType
    description: str
    severity: IncidentSeverity
    incident_date: date
    academic_year_id: uuid.UUID
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BehaviourListResponse(BaseModel):
    items: list[BehaviourResponse]
    total: int

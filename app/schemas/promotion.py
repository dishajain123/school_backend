import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.utils.enums import PromotionStatus


class PromotionStatusUpdate(BaseModel):
    promotion_status: PromotionStatus


class AcademicHistoryResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    standard_id: uuid.UUID
    section: Optional[str] = None
    academic_year_id: uuid.UUID
    promoted_to_standard_id: Optional[uuid.UUID] = None
    promotion_status: PromotionStatus
    recorded_at: datetime
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RolloverResponse(BaseModel):
    processed: int
    skipped: int

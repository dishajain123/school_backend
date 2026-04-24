import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class TimetableUploadResponse(BaseModel):
    id: uuid.UUID
    standard_id: uuid.UUID
    section: Optional[str] = None
    academic_year_id: uuid.UUID
    file_key: str
    file_url: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    uploaded_by: Optional[uuid.UUID] = None
    uploaded_by_name: Optional[str] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimetableResponse(BaseModel):
    id: uuid.UUID
    standard_id: uuid.UUID
    section: Optional[str] = None
    academic_year_id: uuid.UUID
    file_key: str
    file_url: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    uploaded_by: Optional[uuid.UUID] = None
    uploaded_by_name: Optional[str] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

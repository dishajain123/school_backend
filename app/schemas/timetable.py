import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TimetableUploadResponse(BaseModel):
    id: uuid.UUID
    standard_id: uuid.UUID
    academic_year_id: uuid.UUID
    file_key: str
    file_url: str
    uploaded_by: Optional[uuid.UUID] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimetableResponse(BaseModel):
    id: uuid.UUID
    standard_id: uuid.UUID
    academic_year_id: uuid.UUID
    file_key: str
    file_url: str
    uploaded_by: Optional[uuid.UUID] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

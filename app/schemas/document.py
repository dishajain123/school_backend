import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.utils.enums import DocumentType, DocumentStatus


class DocumentRequest(BaseModel):
    student_id: uuid.UUID
    document_type: DocumentType
    academic_year_id: Optional[uuid.UUID] = None


class DocumentResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    document_type: DocumentType
    file_key: Optional[str] = None
    status: DocumentStatus
    requested_at: datetime
    generated_at: Optional[datetime] = None
    academic_year_id: uuid.UUID
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class DocumentDownloadResponse(BaseModel):
    status: DocumentStatus
    url: Optional[str] = None

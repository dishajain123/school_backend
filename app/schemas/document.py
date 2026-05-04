import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.utils.enums import DocumentType, DocumentStatus


class DocumentRequest(BaseModel):
    student_id: uuid.UUID
    document_type: DocumentType
    academic_year_id: Optional[uuid.UUID] = None
    note: Optional[str] = Field(None, max_length=500)


class DocumentResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    document_type: DocumentType
    document_type_id: Optional[str] = None
    file_key: Optional[str] = None
    file_url: Optional[str] = None
    is_synthetic: bool = Field(
        default=False,
        description="True when this row is not persisted — admin list filler for missing slots.",
    )
    status: DocumentStatus
    requested_at: datetime
    generated_at: Optional[datetime] = None
    admin_comment: Optional[str] = None
    review_note: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[uuid.UUID] = None
    student_name: Optional[str] = None
    student_admission_number: Optional[str] = None
    parent_name: Optional[str] = None
    academic_year_id: uuid.UUID
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    required_documents: list["DocumentRequirementStatusResponse"] = Field(
        default_factory=list
    )


class DocumentDownloadResponse(BaseModel):
    status: DocumentStatus
    url: Optional[str] = None


class DocumentVerifyRequest(BaseModel):
    approve: bool = True
    reason: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def reject_requires_comment(self) -> "DocumentVerifyRequest":
        if not self.approve:
            if not (self.reason or "").strip():
                raise ValueError("Rejection requires a comment (reason)")
        return self


class DocumentRequirementItem(BaseModel):
    document_type: DocumentType
    is_mandatory: bool = True
    note: Optional[str] = Field(None, max_length=500)
    academic_year_id: Optional[uuid.UUID] = None
    standard_id: Optional[uuid.UUID] = None


class DocumentRequirementsUpsertRequest(BaseModel):
    items: list[DocumentRequirementItem] = Field(default_factory=list)


class DocumentRequirementResponse(BaseModel):
    document_type: DocumentType
    is_mandatory: bool
    note: Optional[str] = None
    academic_year_id: Optional[uuid.UUID] = None
    standard_id: Optional[uuid.UUID] = None


class DocumentRequirementsResponse(BaseModel):
    items: list[DocumentRequirementResponse]


class DocumentRequirementStatusResponse(BaseModel):
    document_type: DocumentType
    is_mandatory: bool
    note: Optional[str] = None
    latest_document_id: Optional[uuid.UUID] = None
    latest_status: Optional[DocumentStatus] = None
    uploaded_at: Optional[datetime] = None
    review_note: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[uuid.UUID] = None
    needs_reupload: bool = False
    is_completed: bool = False
    academic_year_id: Optional[uuid.UUID] = None
    standard_id: Optional[uuid.UUID] = None

import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class StudentCreate(BaseModel):
    user_id: Optional[uuid.UUID] = None
    parent_id: uuid.UUID
    standard_id: Optional[uuid.UUID] = None
    academic_year_id: Optional[uuid.UUID] = None
    section: Optional[str] = Field(None, max_length=10)
    roll_number: Optional[str] = Field(None, max_length=20)
    admission_number: str = Field(..., min_length=1, max_length=50)
    date_of_birth: Optional[date] = None
    admission_date: Optional[date] = None


class StudentUpdate(BaseModel):
    standard_id: Optional[uuid.UUID] = None
    academic_year_id: Optional[uuid.UUID] = None
    section: Optional[str] = Field(None, max_length=10)
    roll_number: Optional[str] = Field(None, max_length=20)
    date_of_birth: Optional[date] = None
    admission_date: Optional[date] = None
    user_id: Optional[uuid.UUID] = None


from app.utils.enums import PromotionStatus


class StudentPromotionUpdate(BaseModel):
    promotion_status: PromotionStatus


class StudentBulkPromotionUpdate(BaseModel):
    student_ids: list[uuid.UUID] = Field(..., min_length=1)
    promotion_status: PromotionStatus


class StudentResponse(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID]
    student_name: Optional[str] = None
    school_id: uuid.UUID
    parent_id: uuid.UUID
    standard_id: Optional[uuid.UUID]
    academic_year_id: Optional[uuid.UUID]
    section: Optional[str]
    roll_number: Optional[str]
    admission_number: str
    date_of_birth: Optional[date]
    admission_date: Optional[date]
    is_promoted: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StudentListResponse(BaseModel):
    items: list[StudentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class StudentBulkPromotionResponse(BaseModel):
    updated_count: int
    items: list[StudentResponse]


class StudentSectionCreateRequest(BaseModel):
    standard_id: uuid.UUID
    section: str = Field(..., min_length=1, max_length=10)
    academic_year_id: Optional[uuid.UUID] = None


class StudentSectionCreateResponse(BaseModel):
    standard_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID] = None
    section: str
    sections: list[str]

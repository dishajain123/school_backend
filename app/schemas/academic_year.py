import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class AcademicYearCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=20, examples=["2024-25"])
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_dates(self) -> "AcademicYearCreate":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class AcademicYearUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=20)
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "AcademicYearUpdate":
        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                raise ValueError("end_date must be after start_date")
        return self


class AcademicYearResponse(BaseModel):
    id: uuid.UUID
    name: str
    start_date: date
    end_date: date
    is_active: bool
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AcademicYearListResponse(BaseModel):
    items: list[AcademicYearResponse]
    total: int
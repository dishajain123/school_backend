import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Standard ──────────────────────────────────────────────────────────────────

class StandardCreate(BaseModel):
    name: str = Field(..., max_length=50)
    level: int = Field(..., ge=1, le=12)
    academic_year_id: Optional[uuid.UUID] = None

    model_config = {"str_strip_whitespace": True}


class StandardUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=50)
    level: Optional[int] = Field(None, ge=1, le=12)
    academic_year_id: Optional[uuid.UUID] = None

    model_config = {"str_strip_whitespace": True}


class StandardResponse(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID]
    name: str
    level: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StandardListResponse(BaseModel):
    items: list[StandardResponse]
    total: int


# ── Subject ───────────────────────────────────────────────────────────────────

class SubjectCreate(BaseModel):
    standard_id: uuid.UUID
    name: str = Field(..., max_length=100)
    code: str = Field(..., max_length=20)

    model_config = {"str_strip_whitespace": True}


class SubjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    code: Optional[str] = Field(None, max_length=20)

    model_config = {"str_strip_whitespace": True}


class SubjectResponse(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    standard_id: uuid.UUID
    name: str
    code: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubjectListResponse(BaseModel):
    items: list[SubjectResponse]
    total: int


# ── GradeMaster ───────────────────────────────────────────────────────────────

class GradeMasterCreate(BaseModel):
    min_percent: float = Field(..., ge=0, le=100)
    max_percent: float = Field(..., ge=0, le=100)
    grade_letter: str = Field(..., max_length=5)
    grade_point: float = Field(..., ge=0, le=10)

    model_config = {"str_strip_whitespace": True}


class GradeMasterUpdate(BaseModel):
    min_percent: Optional[float] = Field(None, ge=0, le=100)
    max_percent: Optional[float] = Field(None, ge=0, le=100)
    grade_letter: Optional[str] = Field(None, max_length=5)
    grade_point: Optional[float] = Field(None, ge=0, le=10)

    model_config = {"str_strip_whitespace": True}


class GradeMasterResponse(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    min_percent: float
    max_percent: float
    grade_letter: str
    grade_point: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GradeMasterListResponse(BaseModel):
    items: list[GradeMasterResponse]
    total: int


# ── Grade lookup result ───────────────────────────────────────────────────────

class GradeLookupResponse(BaseModel):
    percent: float
    grade_letter: str
    grade_point: float
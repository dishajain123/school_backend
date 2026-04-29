# 🆕 NEW FILE
# app/schemas/my_class.py
"""
Pydantic v2 schemas for the My Class module.

Naming convention matches existing schemas (e.g. app/schemas/parent.py):
  - XxxCreate    → POST body
  - XxxUpdate    → PATCH body
  - XxxResponse  → single item response
  - XxxListResponse → paginated list
"""

import uuid
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Shared / embedded sub-schemas
# ─────────────────────────────────────────────────────────────────────────────

class _IdName(BaseModel):
    id: uuid.UUID
    name: str
    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# Chapter
# ─────────────────────────────────────────────────────────────────────────────

class ChapterCreate(BaseModel):
    subject_id: uuid.UUID
    standard_id: uuid.UUID
    section_id: uuid.UUID
    academic_year_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    order_index: int = Field(0, ge=0)

    model_config = {"str_strip_whitespace": True}


class ChapterUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    order_index: Optional[int] = Field(None, ge=0)
    is_locked: Optional[bool] = None

    model_config = {"str_strip_whitespace": True}


class ChapterResponse(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    subject_id: uuid.UUID
    standard_id: uuid.UUID
    section_id: uuid.UUID
    academic_year_id: uuid.UUID
    created_by: Optional[uuid.UUID]
    title: str
    description: Optional[str]
    order_index: int
    is_locked: bool
    topic_count: int = 0          # computed at query time
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChapterListResponse(BaseModel):
    items: list[ChapterResponse]
    total: int


# ─────────────────────────────────────────────────────────────────────────────
# Topic
# ─────────────────────────────────────────────────────────────────────────────

class TopicCreate(BaseModel):
    chapter_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    order_index: int = Field(0, ge=0)

    model_config = {"str_strip_whitespace": True}


class TopicUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    order_index: Optional[int] = Field(None, ge=0)
    is_locked: Optional[bool] = None

    model_config = {"str_strip_whitespace": True}


class TopicResponse(BaseModel):
    id: uuid.UUID
    chapter_id: uuid.UUID
    created_by: Optional[uuid.UUID]
    title: str
    description: Optional[str]
    order_index: int
    is_locked: bool
    content_count: int = 0        # computed at query time
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TopicListResponse(BaseModel):
    items: list[TopicResponse]
    total: int


# ─────────────────────────────────────────────────────────────────────────────
# ContentItem
# ─────────────────────────────────────────────────────────────────────────────

VALID_CONTENT_TYPES = {"note", "file", "link", "quiz"}


class ContentItemCreate(BaseModel):
    topic_id: uuid.UUID
    content_type: str = Field(..., description="note | file | link | quiz")

    # Denormalized context (decision #6) — required at creation
    academic_year_id: uuid.UUID
    standard_id: uuid.UUID
    section_id: uuid.UUID
    subject_id: uuid.UUID

    title: Optional[str] = Field(None, max_length=255)
    order_index: int = Field(0, ge=0)
    metadata_json: Optional[dict[str, Any]] = None

    # type=note
    note_text: Optional[str] = None

    # type=file  (file_key provided after MinIO upload)
    file_key: Optional[str] = Field(None, max_length=500)
    file_name: Optional[str] = Field(None, max_length=255)
    file_mime_type: Optional[str] = Field(None, max_length=100)

    # type=link
    link_url: Optional[str] = Field(None, max_length=2000)
    link_title: Optional[str] = Field(None, max_length=255)

    # type=quiz — quiz_id supplied after Quiz is created
    quiz_id: Optional[uuid.UUID] = None

    model_config = {"str_strip_whitespace": True}

    @field_validator("content_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_CONTENT_TYPES:
            raise ValueError(f"content_type must be one of {VALID_CONTENT_TYPES}")
        return v


class ContentItemUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    order_index: Optional[int] = Field(None, ge=0)
    is_locked: Optional[bool] = None
    metadata_json: Optional[dict[str, Any]] = None

    note_text: Optional[str] = None
    file_key: Optional[str] = Field(None, max_length=500)
    file_name: Optional[str] = Field(None, max_length=255)
    file_mime_type: Optional[str] = Field(None, max_length=100)
    link_url: Optional[str] = Field(None, max_length=2000)
    link_title: Optional[str] = Field(None, max_length=255)
    quiz_id: Optional[uuid.UUID] = None

    model_config = {"str_strip_whitespace": True}


class ContentItemResponse(BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID
    created_by: Optional[uuid.UUID]
    content_type: str

    # Denormalized context
    academic_year_id: uuid.UUID
    standard_id: uuid.UUID
    section_id: uuid.UUID
    subject_id: uuid.UUID
    school_id: uuid.UUID

    title: Optional[str]
    order_index: int
    is_locked: bool
    metadata_json: Optional[dict[str, Any]]

    note_text: Optional[str]
    file_key: Optional[str]
    file_name: Optional[str]
    file_mime_type: Optional[str]
    # file_url: presigned URL injected by service layer (not a DB column)
    file_url: Optional[str] = None

    link_url: Optional[str]
    link_title: Optional[str]
    quiz_id: Optional[uuid.UUID]

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContentItemListResponse(BaseModel):
    items: list[ContentItemResponse]
    total: int


# ─────────────────────────────────────────────────────────────────────────────
# Quiz
# ─────────────────────────────────────────────────────────────────────────────

class QuizCreate(BaseModel):
    topic_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=255)
    instructions: Optional[str] = None
    total_marks: int = Field(0, ge=0)
    duration_minutes: Optional[int] = Field(None, ge=1)

    model_config = {"str_strip_whitespace": True}


class QuizUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    instructions: Optional[str] = None
    total_marks: Optional[int] = Field(None, ge=0)
    duration_minutes: Optional[int] = Field(None, ge=1)
    is_locked: Optional[bool] = None

    model_config = {"str_strip_whitespace": True}


class QuizResponse(BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID
    school_id: uuid.UUID
    created_by: Optional[uuid.UUID]
    title: str
    instructions: Optional[str]
    total_marks: int
    duration_minutes: Optional[int]
    is_locked: bool
    question_count: int = 0       # computed
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# Question
# ─────────────────────────────────────────────────────────────────────────────

VALID_QUESTION_TYPES = {"mcq", "true_false", "short_answer"}


class QuestionCreate(BaseModel):
    quiz_id: uuid.UUID
    question_text: str = Field(..., min_length=1)
    question_type: str = Field("mcq", description="mcq | true_false | short_answer")
    options_json: Optional[list[str]] = None
    correct_answer: str = Field(..., min_length=1, max_length=500)
    marks: int = Field(1, ge=0)
    explanation: Optional[str] = None
    order_index: int = Field(0, ge=0)

    model_config = {"str_strip_whitespace": True}

    @field_validator("question_type")
    @classmethod
    def validate_qtype(cls, v: str) -> str:
        if v not in VALID_QUESTION_TYPES:
            raise ValueError(f"question_type must be one of {VALID_QUESTION_TYPES}")
        return v


class QuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    question_type: Optional[str] = None
    options_json: Optional[list[str]] = None
    correct_answer: Optional[str] = Field(None, max_length=500)
    marks: Optional[int] = Field(None, ge=0)
    explanation: Optional[str] = None
    order_index: Optional[int] = Field(None, ge=0)

    model_config = {"str_strip_whitespace": True}


class QuestionResponse(BaseModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    question_text: str
    question_type: str
    options_json: Optional[list[str]]
    correct_answer: str
    marks: int
    explanation: Optional[str]
    order_index: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# Variant for students — correct_answer is hidden until submitted
class QuestionPublicResponse(BaseModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    question_text: str
    question_type: str
    options_json: Optional[list[str]]
    marks: int
    order_index: int

    model_config = {"from_attributes": True}


class QuizWithQuestionsResponse(QuizResponse):
    """Full quiz payload for teacher view — includes correct answers."""
    questions: list[QuestionResponse] = []


class QuizPublicResponse(QuizResponse):
    """Quiz payload for students — questions without correct answers."""
    questions: list[QuestionPublicResponse] = []


# ─────────────────────────────────────────────────────────────────────────────
# Attempt
# ─────────────────────────────────────────────────────────────────────────────

class AttemptCreate(BaseModel):
    """Student submits their answers."""
    quiz_id: uuid.UUID
    answers_json: dict[str, str] = Field(
        ...,
        description="Map of question_id (str) → student_answer (str)"
    )

    model_config = {"str_strip_whitespace": True}


class AttemptResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    quiz_id: uuid.UUID
    academic_year_id: uuid.UUID
    answers_json: Optional[dict[str, Any]]
    score: int
    total_marks: int
    is_completed: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AttemptResultResponse(AttemptResponse):
    """Extended result — includes per-question breakdown."""
    percentage: float = 0.0
    questions_with_results: list[dict[str, Any]] = []


class AttemptListResponse(BaseModel):
    items: list[AttemptResponse]
    total: int
    best_score: Optional[int] = None
    latest_attempt_id: Optional[uuid.UUID] = None


# ─────────────────────────────────────────────────────────────────────────────
# Subject summary (returned when student lists subjects for a year)
# ─────────────────────────────────────────────────────────────────────────────

class SubjectSummaryForClass(BaseModel):
    """
    Summary of a subject available to a student for a given year/class/section.
    Derived from TeacherClassSubject assignments.
    """
    subject_id: uuid.UUID
    subject_name: str
    subject_code: str
    standard_id: uuid.UUID
    section_id: uuid.UUID
    academic_year_id: uuid.UUID
    teacher_name: Optional[str] = None
    chapter_count: int = 0

    model_config = {"from_attributes": True}


class SubjectListForClassResponse(BaseModel):
    items: list[SubjectSummaryForClass]
    total: int
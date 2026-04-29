# 🆕 NEW FILE
# app/models/my_class.py
"""
My Class module — structured learning content hierarchy.

Hierarchy:  Subject → Chapter → Topic → ContentItem (note/file/link/quiz)

Design decisions (locked):
- Chapter stores section_id (UUID FK) — aligned with StudentYearMapping
- ContentItem stores denormalized context fields for fast filtering
- is_locked flag on every entity for exam freeze / manual lock
- order_index for drag-and-drop ordering in UI
- Quiz is a first-class ContentItem (ContentItem.type = "quiz", ContentItem.quiz_id = FK)
- Multiple attempts allowed per student per quiz (no unique constraint)
- file_key stored (not URL) — presigned URLs generated at fetch time
"""

from __future__ import annotations

import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel

if TYPE_CHECKING:
    from app.models.masters import Subject, Standard
    from app.models.section import Section
    from app.models.academic_year import AcademicYear
    from app.models.user import User
    from app.models.student import Student


# ─────────────────────────────────────────────────────────────────────────────
# Chapter
# ─────────────────────────────────────────────────────────────────────────────

class Chapter(BaseModel):
    """
    Top-level grouping within a subject for a specific class/section/year.

    One teacher assignment (standard + section + subject + year) owns N chapters.
    section_id is a UUID FK to sections table — aligned with StudentYearMapping.
    """
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint(
            "subject_id", "standard_id", "section_id",
            "academic_year_id", "title",
            name="uq_chapter_subject_class_section_year_title",
        ),
    )

    # 🔑 Context (who owns this chapter)
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # section_id: UUID FK (decision #1 — aligned with StudentYearMapping)
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 📝 Content
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 🔢 Ordering
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 🔒 Locking (decision #7)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    subject: Mapped["Subject"] = relationship("Subject", foreign_keys=[subject_id], lazy="select")
    standard: Mapped["Standard"] = relationship("Standard", foreign_keys=[standard_id], lazy="select")
    section: Mapped["Section"] = relationship("Section", foreign_keys=[section_id], lazy="select")
    academic_year: Mapped["AcademicYear"] = relationship("AcademicYear", foreign_keys=[academic_year_id], lazy="select")
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by], lazy="select")
    topics: Mapped[list["Topic"]] = relationship(
        "Topic",
        back_populates="chapter",
        cascade="all, delete-orphan",
        order_by="Topic.order_index",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Topic
# ─────────────────────────────────────────────────────────────────────────────

class Topic(BaseModel):
    """
    Sub-unit within a Chapter.  Chapter → N Topics → N ContentItems.
    """
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint(
            "chapter_id", "title",
            name="uq_topic_chapter_title",
        ),
    )

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 📝 Content
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 🔢 Ordering
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 🔒 Locking
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    chapter: Mapped["Chapter"] = relationship("Chapter", back_populates="topics", lazy="select")
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by], lazy="select")
    content_items: Mapped[list["ContentItem"]] = relationship(
        "ContentItem",
        back_populates="topic",
        cascade="all, delete-orphan",
        order_by="ContentItem.order_index",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ContentItem
# ─────────────────────────────────────────────────────────────────────────────

class ContentItem(BaseModel):
    """
    Leaf node of the hierarchy.  Type: note | file | link | quiz.

    Decision #6: denormalized context fields (academic_year_id, standard_id,
    section_id, subject_id) stored directly for fast filtering without deep joins.

    Decision #9: quiz is a ContentItem with type="quiz" and quiz_id FK set.
    Decision #2: file_key stored (not URL) — presigned URL generated at read time.
    """
    __tablename__ = "content_items"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Denormalized context (decision #6) ────────────────────────────────────
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Type discriminator ────────────────────────────────────────────────────
    # Allowed values: "note" | "file" | "link" | "quiz"
    content_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # ── Payload fields (only the relevant one is populated per type) ──────────
    # type = "note"
    note_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # type = "file"  (decision #2 — file_key, NOT raw URL)
    file_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # type = "link"
    link_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    link_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # type = "quiz"  (decision #9 — quiz is a content item)
    quiz_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quizzes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Common metadata ───────────────────────────────────────────────────────
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # 🔢 Ordering (decision #8)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 🔒 Locking (decision #7)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    topic: Mapped["Topic"] = relationship("Topic", back_populates="content_items", lazy="select")
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by], lazy="select")
    quiz: Mapped[Optional["Quiz"]] = relationship("Quiz", foreign_keys=[quiz_id], lazy="select")


# ─────────────────────────────────────────────────────────────────────────────
# Quiz
# ─────────────────────────────────────────────────────────────────────────────

class Quiz(BaseModel):
    """
    Quiz entity.  Linked to ContentItem via ContentItem.quiz_id.
    A Quiz without a ContentItem row is orphaned — always create ContentItem first.
    """
    __tablename__ = "quizzes"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    total_marks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # duration in minutes; None = untimed
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 🔒 Locking (decision #7)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    topic: Mapped["Topic"] = relationship("Topic", foreign_keys=[topic_id], lazy="select")
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by], lazy="select")
    questions: Mapped[list["Question"]] = relationship(
        "Question",
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="Question.order_index",
        lazy="select",
    )
    attempts: Mapped[list["Attempt"]] = relationship(
        "Attempt",
        back_populates="quiz",
        cascade="all, delete-orphan",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Question
# ─────────────────────────────────────────────────────────────────────────────

class Question(BaseModel):
    """
    Individual question inside a Quiz.
    options_json: list of option strings, e.g. ["Paris", "London", "Berlin", "Rome"]
    correct_answer: index (0-based) into options_json for MCQ,
                    or plain string for short-answer.
    """
    __tablename__ = "questions"

    quiz_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # e.g. "mcq" | "true_false" | "short_answer"
    question_type: Mapped[str] = mapped_column(String(30), nullable=False, default="mcq")
    options_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    correct_answer: Mapped[str] = mapped_column(String(500), nullable=False)
    marks: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 🔢 Ordering
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Relationships ─────────────────────────────────────────────────────────
    quiz: Mapped["Quiz"] = relationship("Quiz", back_populates="questions", lazy="select")


# ─────────────────────────────────────────────────────────────────────────────
# Attempt
# ─────────────────────────────────────────────────────────────────────────────

class Attempt(BaseModel):
    """
    Student's quiz attempt.

    Decision #3: multiple attempts allowed — NO unique(student_id, quiz_id).
    All attempts stored; latest + best score returned by service layer.
    Only allowed for current academic year (enforced in service).
    """
    __tablename__ = "attempts"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # answers_json: { "question_id": "student_answer", ... }
    answers_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_marks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # submitted_at is stored in created_at (inherited from BaseModel)
    # is_completed = False means in-progress / abandoned
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    quiz: Mapped["Quiz"] = relationship("Quiz", back_populates="attempts", lazy="select")
# 🆕 NEW FILE
# app/repositories/my_class.py
"""
Repository layer for the My Class module.

Pattern matches existing repositories (e.g. app/repositories/masters.py):
  - Each class wraps one model
  - All methods are async
  - No business logic — pure DB access
  - Services compose these repos
"""

import uuid
from typing import Optional

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.my_class import (
    Attempt,
    Chapter,
    ContentItem,
    Question,
    Quiz,
    Topic,
)


# ─────────────────────────────────────────────────────────────────────────────
# ChapterRepository
# ─────────────────────────────────────────────────────────────────────────────

class ChapterRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict) -> Chapter:
        obj = Chapter(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self,
        chapter_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> Optional[Chapter]:
        result = await self.db.execute(
            select(Chapter).where(
                Chapter.id == chapter_id,
                Chapter.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_subject(
        self,
        school_id: uuid.UUID,
        subject_id: uuid.UUID,
        standard_id: uuid.UUID,
        section_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> tuple[list[Chapter], int]:
        filters = and_(
            Chapter.school_id == school_id,
            Chapter.subject_id == subject_id,
            Chapter.standard_id == standard_id,
            Chapter.section_id == section_id,
            Chapter.academic_year_id == academic_year_id,
        )
        count_q = select(func.count(Chapter.id)).where(filters)
        total = (await self.db.execute(count_q)).scalar_one()

        rows = await self.db.execute(
            select(Chapter)
            .where(filters)
            .order_by(Chapter.order_index.asc(), Chapter.created_at.asc())
        )
        return list(rows.scalars().all()), total

    async def update(self, obj: Chapter, data: dict) -> Chapter:
        for k, v in data.items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: Chapter) -> None:
        await self.db.delete(obj)
        await self.db.flush()

    async def count_topics(self, chapter_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(Topic.id)).where(Topic.chapter_id == chapter_id)
        )
        return result.scalar_one()

    async def duplicate_exists(
        self,
        school_id: uuid.UUID,
        subject_id: uuid.UUID,
        standard_id: uuid.UUID,
        section_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        title: str,
        exclude_id: Optional[uuid.UUID] = None,
    ) -> bool:
        stmt = select(Chapter.id).where(
            Chapter.school_id == school_id,
            Chapter.subject_id == subject_id,
            Chapter.standard_id == standard_id,
            Chapter.section_id == section_id,
            Chapter.academic_year_id == academic_year_id,
            func.lower(Chapter.title) == title.lower(),
        )
        if exclude_id:
            stmt = stmt.where(Chapter.id != exclude_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None


# ─────────────────────────────────────────────────────────────────────────────
# TopicRepository
# ─────────────────────────────────────────────────────────────────────────────

class TopicRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict) -> Topic:
        obj = Topic(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, topic_id: uuid.UUID) -> Optional[Topic]:
        result = await self.db.execute(
            select(Topic).where(Topic.id == topic_id)
        )
        return result.scalar_one_or_none()

    async def list_by_chapter(
        self,
        chapter_id: uuid.UUID,
    ) -> tuple[list[Topic], int]:
        count_q = select(func.count(Topic.id)).where(Topic.chapter_id == chapter_id)
        total = (await self.db.execute(count_q)).scalar_one()

        rows = await self.db.execute(
            select(Topic)
            .where(Topic.chapter_id == chapter_id)
            .order_by(Topic.order_index.asc(), Topic.created_at.asc())
        )
        return list(rows.scalars().all()), total

    async def update(self, obj: Topic, data: dict) -> Topic:
        for k, v in data.items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: Topic) -> None:
        await self.db.delete(obj)
        await self.db.flush()

    async def count_content(self, topic_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(ContentItem.id)).where(
                ContentItem.topic_id == topic_id
            )
        )
        return result.scalar_one()


# ─────────────────────────────────────────────────────────────────────────────
# ContentItemRepository
# ─────────────────────────────────────────────────────────────────────────────

class ContentItemRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict) -> ContentItem:
        obj = ContentItem(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self,
        item_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> Optional[ContentItem]:
        result = await self.db.execute(
            select(ContentItem).where(
                ContentItem.id == item_id,
                ContentItem.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_topic(
        self,
        topic_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> tuple[list[ContentItem], int]:
        filters = and_(
            ContentItem.topic_id == topic_id,
            ContentItem.school_id == school_id,
        )
        count_q = select(func.count(ContentItem.id)).where(filters)
        total = (await self.db.execute(count_q)).scalar_one()

        rows = await self.db.execute(
            select(ContentItem)
            .where(filters)
            .order_by(ContentItem.order_index.asc(), ContentItem.created_at.asc())
        )
        return list(rows.scalars().all()), total

    async def list_by_context(
        self,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        standard_id: uuid.UUID,
        section_id: uuid.UUID,
        subject_id: uuid.UUID,
        content_type: Optional[str] = None,
    ) -> tuple[list[ContentItem], int]:
        """Fast-path query using denormalized context fields."""
        filters = and_(
            ContentItem.school_id == school_id,
            ContentItem.academic_year_id == academic_year_id,
            ContentItem.standard_id == standard_id,
            ContentItem.section_id == section_id,
            ContentItem.subject_id == subject_id,
        )
        if content_type:
            filters = and_(filters, ContentItem.content_type == content_type)

        count_q = select(func.count(ContentItem.id)).where(filters)
        total = (await self.db.execute(count_q)).scalar_one()

        rows = await self.db.execute(
            select(ContentItem)
            .where(filters)
            .order_by(ContentItem.order_index.asc(), ContentItem.created_at.asc())
        )
        return list(rows.scalars().all()), total

    async def update(self, obj: ContentItem, data: dict) -> ContentItem:
        for k, v in data.items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: ContentItem) -> None:
        await self.db.delete(obj)
        await self.db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# QuizRepository
# ─────────────────────────────────────────────────────────────────────────────

class QuizRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict) -> Quiz:
        obj = Quiz(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self,
        quiz_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> Optional[Quiz]:
        result = await self.db.execute(
            select(Quiz).where(
                Quiz.id == quiz_id,
                Quiz.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def update(self, obj: Quiz, data: dict) -> Quiz:
        for k, v in data.items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: Quiz) -> None:
        await self.db.delete(obj)
        await self.db.flush()

    async def count_questions(self, quiz_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(Question.id)).where(Question.quiz_id == quiz_id)
        )
        return result.scalar_one()


# ─────────────────────────────────────────────────────────────────────────────
# QuestionRepository
# ─────────────────────────────────────────────────────────────────────────────

class QuestionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict) -> Question:
        obj = Question(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, question_id: uuid.UUID) -> Optional[Question]:
        result = await self.db.execute(
            select(Question).where(Question.id == question_id)
        )
        return result.scalar_one_or_none()

    async def list_by_quiz(
        self,
        quiz_id: uuid.UUID,
    ) -> list[Question]:
        rows = await self.db.execute(
            select(Question)
            .where(Question.quiz_id == quiz_id)
            .order_by(Question.order_index.asc(), Question.created_at.asc())
        )
        return list(rows.scalars().all())

    async def update(self, obj: Question, data: dict) -> Question:
        for k, v in data.items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: Question) -> None:
        await self.db.delete(obj)
        await self.db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# AttemptRepository
# ─────────────────────────────────────────────────────────────────────────────

class AttemptRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict) -> Attempt:
        obj = Attempt(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, attempt_id: uuid.UUID) -> Optional[Attempt]:
        result = await self.db.execute(
            select(Attempt).where(Attempt.id == attempt_id)
        )
        return result.scalar_one_or_none()

    async def list_by_student_quiz(
        self,
        student_id: uuid.UUID,
        quiz_id: uuid.UUID,
    ) -> list[Attempt]:
        """Returns all attempts for a student on a specific quiz, latest first."""
        rows = await self.db.execute(
            select(Attempt)
            .where(
                Attempt.student_id == student_id,
                Attempt.quiz_id == quiz_id,
            )
            .order_by(Attempt.created_at.desc())
        )
        return list(rows.scalars().all())

    async def list_by_quiz(
        self,
        quiz_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> list[Attempt]:
        """Returns all student attempts for a quiz (teacher/admin view)."""
        rows = await self.db.execute(
            select(Attempt)
            .where(
                Attempt.quiz_id == quiz_id,
                Attempt.school_id == school_id,
            )
            .order_by(Attempt.created_at.desc())
        )
        return list(rows.scalars().all())

    async def get_best_score(
        self,
        student_id: uuid.UUID,
        quiz_id: uuid.UUID,
    ) -> Optional[int]:
        result = await self.db.execute(
            select(func.max(Attempt.score)).where(
                Attempt.student_id == student_id,
                Attempt.quiz_id == quiz_id,
                Attempt.is_completed == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def update(self, obj: Attempt, data: dict) -> Attempt:
        for k, v in data.items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj
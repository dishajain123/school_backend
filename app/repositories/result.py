import uuid
from typing import Optional

from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.exam import Exam
from app.models.result import Result


def _exam_with_relations(stmt):
    return stmt.options(
        selectinload(Exam.standard),
        selectinload(Exam.academic_year),
    )


def _result_with_relations(stmt):
    return stmt.options(
        selectinload(Result.student),
        selectinload(Result.subject),
        selectinload(Result.grade),
    )


class ResultRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # Exams
    async def create_exam(self, data: dict) -> Exam:
        obj = Exam(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_exam_by_id(self, exam_id: uuid.UUID, school_id: uuid.UUID) -> Optional[Exam]:
        result = await self.db.execute(
            _exam_with_relations(
                select(Exam).where(
                    and_(
                        Exam.id == exam_id,
                        Exam.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_exam_duplicate(
        self, school_id: uuid.UUID, standard_id: uuid.UUID, academic_year_id: uuid.UUID, name: str
    ) -> Optional[Exam]:
        result = await self.db.execute(
            select(Exam).where(
                and_(
                    Exam.school_id == school_id,
                    Exam.standard_id == standard_id,
                    Exam.academic_year_id == academic_year_id,
                    Exam.name == name,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_exams(
        self,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        student_id: Optional[uuid.UUID] = None,
    ) -> list[Exam]:
        stmt = select(Exam).where(Exam.school_id == school_id)

        if academic_year_id is not None:
            stmt = stmt.where(Exam.academic_year_id == academic_year_id)
        if standard_id is not None:
            stmt = stmt.where(Exam.standard_id == standard_id)
        if student_id is not None:
            stmt = stmt.join(
                Result,
                and_(
                    Result.exam_id == Exam.id,
                    Result.student_id == student_id,
                    Result.school_id == school_id,
                ),
            ).distinct()

        stmt = stmt.order_by(Exam.start_date.desc(), Exam.created_at.desc())
        result = await self.db.execute(_exam_with_relations(stmt))
        return list(result.scalars().all())

    # Results
    async def create_result(self, data: dict) -> Result:
        obj = Result(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_result_existing(
        self, exam_id: uuid.UUID, student_id: uuid.UUID, subject_id: uuid.UUID
    ) -> Optional[Result]:
        result = await self.db.execute(
            select(Result).where(
                and_(
                    Result.exam_id == exam_id,
                    Result.student_id == student_id,
                    Result.subject_id == subject_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_results(
        self,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
        exam_id: uuid.UUID,
        published_only: bool = False,
    ) -> list[Result]:
        stmt = select(Result).where(
            and_(
                Result.school_id == school_id,
                Result.student_id == student_id,
                Result.exam_id == exam_id,
            )
        )
        if published_only:
            stmt = stmt.where(Result.is_published == True)  # noqa: E712

        result = await self.db.execute(_result_with_relations(stmt))
        return list(result.scalars().all())

    async def publish_exam_results(
        self, exam_id: uuid.UUID, school_id: uuid.UUID
    ) -> int:
        result = await self.db.execute(
            update(Result)
            .where(
                and_(
                    Result.exam_id == exam_id,
                    Result.school_id == school_id,
                )
            )
            .values(is_published=True)
        )
        await self.db.flush()
        return result.rowcount  # type: ignore[return-value]

import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.exam_schedule import ExamSeries, ExamScheduleEntry


def _series_with_relations(stmt):
    return stmt.options(
        selectinload(ExamSeries.standard),
        selectinload(ExamSeries.academic_year),
    )


def _entry_with_relations(stmt):
    return stmt.options(selectinload(ExamScheduleEntry.subject))


class ExamScheduleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_series(self, data: dict) -> ExamSeries:
        obj = ExamSeries(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_series_by_id(
        self, series_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[ExamSeries]:
        result = await self.db.execute(
            _series_with_relations(
                select(ExamSeries).where(
                    and_(
                        ExamSeries.id == series_id,
                        ExamSeries.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_series_duplicate(
        self, school_id: uuid.UUID, standard_id: uuid.UUID, academic_year_id: uuid.UUID, name: str
    ) -> Optional[ExamSeries]:
        result = await self.db.execute(
            select(ExamSeries).where(
                and_(
                    ExamSeries.school_id == school_id,
                    ExamSeries.standard_id == standard_id,
                    ExamSeries.academic_year_id == academic_year_id,
                    ExamSeries.name == name,
                )
            )
        )
        return result.scalar_one_or_none()

    async def update_series(self, series: ExamSeries, data: dict) -> ExamSeries:
        for key, value in data.items():
            setattr(series, key, value)
        await self.db.flush()
        await self.db.refresh(series)
        return series

    async def create_entry(self, data: dict) -> ExamScheduleEntry:
        obj = ExamScheduleEntry(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update_entry(self, entry: ExamScheduleEntry, data: dict) -> ExamScheduleEntry:
        for key, value in data.items():
            setattr(entry, key, value)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def get_entry_by_id(
        self, entry_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[ExamScheduleEntry]:
        result = await self.db.execute(
            _entry_with_relations(
                select(ExamScheduleEntry)
                .join(ExamSeries, ExamScheduleEntry.series_id == ExamSeries.id)
                .where(
                    and_(
                        ExamScheduleEntry.id == entry_id,
                        ExamSeries.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_entries_for_series(
        self, series_id: uuid.UUID, school_id: uuid.UUID
    ) -> list[ExamScheduleEntry]:
        result = await self.db.execute(
            _entry_with_relations(
                select(ExamScheduleEntry)
                .join(ExamSeries, ExamScheduleEntry.series_id == ExamSeries.id)
                .where(
                    and_(
                        ExamSeries.id == series_id,
                        ExamSeries.school_id == school_id,
                    )
                )
                .order_by(ExamScheduleEntry.exam_date.asc(), ExamScheduleEntry.start_time.asc())
            )
        )
        return list(result.scalars().all())

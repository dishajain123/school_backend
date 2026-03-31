import uuid
from datetime import date
from typing import Optional
from sqlalchemy import select, func, case, text, and_, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attendance import Attendance
from app.models.student import Student
from app.models.masters import Subject
from app.utils.enums import AttendanceStatus


class AttendanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def bulk_upsert(
        self,
        records: list[dict],
    ) -> tuple[int, int]:
        """
        INSERT ... ON CONFLICT (student_id, subject_id, date)
        DO UPDATE SET status = EXCLUDED.status, updated_at = now()
        Returns (inserted_count, updated_count) approximation via rowcount.
        """
        if not records:
            return 0, 0

        stmt = pg_insert(Attendance).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_attendance_student_subject_date",
            set_={
                "status": stmt.excluded.status,
                "teacher_id": stmt.excluded.teacher_id,
                "updated_at": func.now(),
            },
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        # rowcount reflects total affected rows; we can't easily split insert vs update here
        return result.rowcount, 0  # type: ignore[return-value]

    async def list_by_student(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        month: Optional[int] = None,
        year: Optional[int] = None,
        subject_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[Attendance], int]:
        stmt = (
            select(Attendance)
            .join(Student, Student.id == Attendance.student_id)
            .where(
                Attendance.student_id == student_id,
                Student.school_id == school_id,
            )
        )

        if month is not None:
            stmt = stmt.where(func.extract("month", Attendance.date) == month)
        if year is not None:
            stmt = stmt.where(func.extract("year", Attendance.date) == year)
        if subject_id is not None:
            stmt = stmt.where(Attendance.subject_id == subject_id)

        count_q = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        rows = await self.db.execute(
            stmt.order_by(Attendance.date.desc())
        )
        return list(rows.scalars().all()), total

    async def list_by_class_date(
        self,
        standard_id: uuid.UUID,
        school_id: uuid.UUID,
        record_date: date,
        subject_id: Optional[uuid.UUID] = None,
    ) -> list[Attendance]:
        stmt = (
            select(Attendance)
            .options(selectinload(Attendance.student))
            .join(Student, Student.id == Attendance.student_id)
            .where(
                Attendance.standard_id == standard_id,
                Attendance.date == record_date,
                Student.school_id == school_id,
            )
        )
        if subject_id is not None:
            stmt = stmt.where(Attendance.subject_id == subject_id)

        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_student_subject_stats(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        month: Optional[int] = None,
        year: Optional[int] = None,
    ) -> list[dict]:
        """Returns per-subject attendance counts for analytics."""
        stmt = (
            select(
                Attendance.subject_id,
                Subject.name.label("subject_name"),
                Subject.code.label("subject_code"),
                func.count(Attendance.id).label("total"),
                func.sum(
                    case((Attendance.status == AttendanceStatus.PRESENT, 1), else_=0)
                ).label("present"),
                func.sum(
                    case((Attendance.status == AttendanceStatus.ABSENT, 1), else_=0)
                ).label("absent"),
                func.sum(
                    case((Attendance.status == AttendanceStatus.LATE, 1), else_=0)
                ).label("late"),
            )
            .join(Subject, Subject.id == Attendance.subject_id)
            .join(Student, Student.id == Attendance.student_id)
            .where(
                Attendance.student_id == student_id,
                Student.school_id == school_id,
            )
            .group_by(Attendance.subject_id, Subject.name, Subject.code)
        )

        if month is not None:
            stmt = stmt.where(func.extract("month", Attendance.date) == month)
        if year is not None:
            stmt = stmt.where(func.extract("year", Attendance.date) == year)

        rows = await self.db.execute(stmt)
        return [row._asdict() for row in rows.all()]

    async def get_class_snapshot(
        self,
        standard_id: uuid.UUID,
        school_id: uuid.UUID,
        record_date: date,
        academic_year_id: uuid.UUID,
    ) -> list[dict]:
        """Returns per-student status for a class on a given date."""
        # All students in the class
        students_q = select(Student).where(
            Student.standard_id == standard_id,
            Student.school_id == school_id,
            Student.academic_year_id == academic_year_id,
        )
        student_rows = await self.db.execute(students_q)
        students = student_rows.scalars().all()

        # Attendance records for that date
        att_q = select(Attendance).where(
            Attendance.standard_id == standard_id,
            Attendance.date == record_date,
        )
        att_rows = await self.db.execute(att_q)
        att_map: dict[uuid.UUID, AttendanceStatus] = {
            a.student_id: a.status for a in att_rows.scalars().all()
        }

        return [
            {
                "student_id": s.id,
                "admission_number": s.admission_number,
                "section": s.section or "",
                "status": att_map.get(s.id),
            }
            for s in students
        ]

    async def get_students_below_threshold(
        self,
        standard_id: uuid.UUID,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        threshold: float,
    ) -> list[dict]:
        """Returns students whose overall attendance % is below threshold."""
        subq = (
            select(
                Attendance.student_id,
                (
                    func.sum(
                        case((Attendance.status == AttendanceStatus.PRESENT, 1), else_=0)
                    )
                    * 100.0
                    / func.nullif(func.count(Attendance.id), 0)
                ).label("percentage"),
            )
            .where(
                Attendance.standard_id == standard_id,
                Attendance.academic_year_id == academic_year_id,
            )
            .group_by(Attendance.student_id)
            .subquery()
        )

        stmt = (
            select(
                Student.id.label("student_id"),
                Student.admission_number,
                Student.section,
                subq.c.percentage,
            )
            .join(subq, subq.c.student_id == Student.id)
            .where(
                Student.standard_id == standard_id,
                Student.school_id == school_id,
                Student.academic_year_id == academic_year_id,
                subq.c.percentage < threshold,
            )
            .order_by(subq.c.percentage.asc())
        )

        rows = await self.db.execute(stmt)
        return [row._asdict() for row in rows.all()]
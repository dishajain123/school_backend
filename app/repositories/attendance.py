import uuid
from datetime import date
from typing import Optional
from sqlalchemy import select, func, case, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attendance import Attendance
from app.models.student import Student
from app.models.masters import Subject, Standard
from app.utils.enums import AttendanceStatus


class AttendanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Upsert ────────────────────────────────────────────────────────────────

    async def bulk_upsert(
        self,
        records: list[dict],
    ) -> tuple[int, int]:
        """
        INSERT ... ON CONFLICT (student_id, subject_id, date, lecture_number)
        DO UPDATE SET status = EXCLUDED.status, updated_at = now()
        Returns (inserted_count, updated_count) approximation via rowcount.
        """
        if not records:
            return 0, 0

        stmt = pg_insert(Attendance).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_attendance_student_subject_date_lecture",
            set_={
                "status": stmt.excluded.status,
                "teacher_id": stmt.excluded.teacher_id,
                "section": stmt.excluded.section,
                "updated_at": func.now(),
            },
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount, 0  # type: ignore[return-value]

    # ── Student history ───────────────────────────────────────────────────────

    async def list_by_student(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        month: Optional[int] = None,
        year: Optional[int] = None,
        subject_id: Optional[uuid.UUID] = None,
        lecture_number: Optional[int] = None,
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
        if lecture_number is not None:
            stmt = stmt.where(Attendance.lecture_number == lecture_number)

        count_q = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        rows = await self.db.execute(
            stmt.order_by(Attendance.date.desc(), Attendance.created_at.desc())
        )
        return list(rows.scalars().all()), total

    # ── Class snapshot ────────────────────────────────────────────────────────

    async def list_by_class_date(
        self,
        standard_id: uuid.UUID,
        section: str,
        school_id: uuid.UUID,
        record_date: date,
        academic_year_id: Optional[uuid.UUID] = None,
        subject_id: Optional[uuid.UUID] = None,
        lecture_number: Optional[int] = None,
    ) -> list[Attendance]:
        stmt = (
            select(Attendance)
            .options(selectinload(Attendance.student))
            .join(Student, Student.id == Attendance.student_id)
            .where(
                Attendance.standard_id == standard_id,
                Attendance.section == section,
                Attendance.date == record_date,
                Student.school_id == school_id,
            )
        )
        if academic_year_id is not None:
            stmt = stmt.where(Attendance.academic_year_id == academic_year_id)
        if subject_id is not None:
            stmt = stmt.where(Attendance.subject_id == subject_id)
        if lecture_number is not None:
            stmt = stmt.where(Attendance.lecture_number == lecture_number)

        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    # ── Lecture-wise snapshot (all students, with zeros for unmarked) ─────────

    async def get_lecture_snapshot(
        self,
        standard_id: uuid.UUID,
        section: str,
        subject_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        school_id: uuid.UUID,
        record_date: date,
        lecture_number: int,
    ) -> list[dict]:
        """
        Returns one row per student in the class-section.
        Students with no attendance record get status = None (unmarked).
        Uses a LEFT JOIN so unabsent-marked students are also visible.
        """
        stmt = text("""
            SELECT
                s.id            AS student_id,
                s.admission_number,
                u.full_name     AS student_name,
                s.roll_number,
                a.id            AS attendance_id,
                a.status
            FROM students s
            LEFT JOIN users u ON u.id = s.user_id
            LEFT JOIN attendance a
                ON  a.student_id     = s.id
                AND a.subject_id     = :subject_id
                AND a.date           = :record_date
                AND a.lecture_number = :lecture_number
                AND a.academic_year_id = :academic_year_id
            WHERE
                s.standard_id      = :standard_id
                AND s.section      = :section
                AND s.school_id    = :school_id
                AND s.academic_year_id = :academic_year_id
            ORDER BY s.roll_number NULLS LAST, s.admission_number
        """)
        result = await self.db.execute(stmt, {
            "standard_id": standard_id,
            "section": section,
            "subject_id": subject_id,
            "academic_year_id": academic_year_id,
            "school_id": school_id,
            "record_date": record_date,
            "lecture_number": lecture_number,
        })
        return [dict(row._mapping) for row in result.all()]

    # ── Per-subject stats for a student ──────────────────────────────────────

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

    # ── Monthly summary for a student ─────────────────────────────────────────

    async def get_student_monthly_summary(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        year: Optional[int] = None,
    ) -> list[dict]:
        """Returns month-by-month attendance breakdown for a student."""
        stmt = (
            select(
                func.extract("year", Attendance.date).label("year"),
                func.extract("month", Attendance.date).label("month"),
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
            .join(Student, Student.id == Attendance.student_id)
            .where(
                Attendance.student_id == student_id,
                Student.school_id == school_id,
            )
            .group_by(
                func.extract("year", Attendance.date),
                func.extract("month", Attendance.date),
            )
            .order_by(
                func.extract("year", Attendance.date).asc(),
                func.extract("month", Attendance.date).asc(),
            )
        )
        if year is not None:
            stmt = stmt.where(func.extract("year", Attendance.date) == year)

        rows = await self.db.execute(stmt)
        return [row._asdict() for row in rows.all()]

    # ── Below threshold ───────────────────────────────────────────────────────

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

    # ── Dashboard: class-wise aggregation ────────────────────────────────────

    async def get_class_analytics(
        self,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        standard_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        """
        Returns attendance aggregated by (standard_id, section).
        Filtered to one school + academic year.
        """
        stmt = (
            select(
                Attendance.standard_id,
                Standard.name.label("standard_name"),
                Attendance.section,
                func.count(Attendance.id).label("total_records"),
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
            .join(Standard, Standard.id == Attendance.standard_id)
            .join(Student, Student.id == Attendance.student_id)
            .where(
                Student.school_id == school_id,
                Attendance.academic_year_id == academic_year_id,
            )
            .group_by(Attendance.standard_id, Standard.name, Attendance.section)
            .order_by(Standard.name.asc(), Attendance.section.asc())
        )
        if standard_id is not None:
            stmt = stmt.where(Attendance.standard_id == standard_id)

        rows = await self.db.execute(stmt)
        return [row._asdict() for row in rows.all()]

    # ── Dashboard: subject-wise aggregation (school-wide) ────────────────────

    async def get_school_subject_analytics(
        self,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> list[dict]:
        """School-wide attendance aggregated by subject."""
        stmt = (
            select(
                Attendance.subject_id,
                Subject.name.label("subject_name"),
                Subject.code.label("subject_code"),
                func.count(Attendance.id).label("total_records"),
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
                Student.school_id == school_id,
                Attendance.academic_year_id == academic_year_id,
            )
            .group_by(Attendance.subject_id, Subject.name, Subject.code)
            .order_by(Subject.name.asc())
        )
        rows = await self.db.execute(stmt)
        return [row._asdict() for row in rows.all()]

    # ── Dashboard: top absentees ──────────────────────────────────────────────

    async def get_top_absentees(
        self,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        limit: int = 10,
        standard_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        """
        Returns students with the highest absence count across all subjects.
        Uses a single aggregation query — no N+1.
        """
        from app.models.user import User

        subq = (
            select(
                Attendance.student_id,
                func.count(Attendance.id).label("total_classes"),
                func.sum(
                    case((Attendance.status == AttendanceStatus.ABSENT, 1), else_=0)
                ).label("absences"),
                func.sum(
                    case((Attendance.status == AttendanceStatus.PRESENT, 1), else_=0)
                ).label("present_count"),
            )
            .where(Attendance.academic_year_id == academic_year_id)
            .group_by(Attendance.student_id)
            .subquery()
        )

        stmt = (
            select(
                Student.id.label("student_id"),
                Student.admission_number,
                Student.standard_id,
                Student.section,
                Standard.name.label("standard_name"),
                subq.c.total_classes,
                subq.c.absences,
                subq.c.present_count,
                func.coalesce(User.full_name, "").label("student_name"),
            )
            .join(subq, subq.c.student_id == Student.id)
            .join(Standard, Standard.id == Student.standard_id)
            .outerjoin(User, User.id == Student.user_id)
            .where(
                Student.school_id == school_id,
                Student.academic_year_id == academic_year_id,
                subq.c.absences > 0,
            )
            .order_by(subq.c.absences.desc(), subq.c.total_classes.desc())
            .limit(limit)
        )
        if standard_id is not None:
            stmt = stmt.where(Student.standard_id == standard_id)

        rows = await self.db.execute(stmt)
        return [row._asdict() for row in rows.all()]

    # ── Dashboard: weekly trend ───────────────────────────────────────────────

    async def get_weekly_trend(
        self,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        weeks: int = 8,
    ) -> list[dict]:
        """Returns attendance aggregated by ISO week for the last N weeks."""
        stmt = text("""
            SELECT
                EXTRACT(YEAR FROM a.date)::int          AS period_year,
                EXTRACT(WEEK FROM a.date)::int          AS period_value,
                TO_CHAR(DATE_TRUNC('week', a.date), 'IYYY-"W"IW') AS period_label,
                COUNT(a.id)                             AS total_records,
                SUM(CASE WHEN a.status = 'PRESENT' THEN 1 ELSE 0 END) AS present,
                SUM(CASE WHEN a.status = 'ABSENT'  THEN 1 ELSE 0 END) AS absent,
                SUM(CASE WHEN a.status = 'LATE'    THEN 1 ELSE 0 END) AS late
            FROM attendance a
            JOIN students s ON s.id = a.student_id
            WHERE
                s.school_id            = :school_id
                AND a.academic_year_id = :academic_year_id
                AND a.date >= CURRENT_DATE - (:weeks * 7)
            GROUP BY period_year, period_value, period_label
            ORDER BY period_year ASC, period_value ASC
        """)
        result = await self.db.execute(stmt, {
            "school_id": school_id,
            "academic_year_id": academic_year_id,
            "weeks": weeks,
        })
        return [dict(row._mapping) for row in result.all()]

    # ── Dashboard: monthly trend ──────────────────────────────────────────────

    async def get_monthly_trend(
        self,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        months: int = 6,
    ) -> list[dict]:
        """Returns attendance aggregated by calendar month for the last N months."""
        stmt = text("""
            SELECT
                EXTRACT(YEAR FROM a.date)::int            AS period_year,
                EXTRACT(MONTH FROM a.date)::int           AS period_value,
                TO_CHAR(a.date, 'YYYY-MM')                AS period_label,
                COUNT(a.id)                               AS total_records,
                SUM(CASE WHEN a.status = 'PRESENT' THEN 1 ELSE 0 END) AS present,
                SUM(CASE WHEN a.status = 'ABSENT'  THEN 1 ELSE 0 END) AS absent,
                SUM(CASE WHEN a.status = 'LATE'    THEN 1 ELSE 0 END) AS late
            FROM attendance a
            JOIN students s ON s.id = a.student_id
            WHERE
                s.school_id            = :school_id
                AND a.academic_year_id = :academic_year_id
                AND a.date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month' * (:months - 1)
            GROUP BY period_year, period_value, period_label
            ORDER BY period_year ASC, period_value ASC
        """)
        result = await self.db.execute(stmt, {
            "school_id": school_id,
            "academic_year_id": academic_year_id,
            "months": months,
        })
        return [dict(row._mapping) for row in result.all()]

    # ── School-wide totals (for dashboard header) ─────────────────────────────

    async def get_school_totals(
        self,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> dict:
        """Single-row aggregate: total, present, absent, late for the whole school."""
        stmt = (
            select(
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
            .join(Student, Student.id == Attendance.student_id)
            .where(
                Student.school_id == school_id,
                Attendance.academic_year_id == academic_year_id,
            )
        )
        row = (await self.db.execute(stmt)).one()
        return row._asdict()
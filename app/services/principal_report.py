import uuid
from datetime import date
from decimal import Decimal
from typing import Optional, Union, List, Set

from sqlalchemy import and_, case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ValidationException
from app.models.attendance import Attendance
from app.models.exam import Exam
from app.models.fee import FeeLedger, FeeStructure
from app.models.masters import Subject
from app.models.payment import Payment
from app.models.result import Result
from app.models.student import Student
from app.models.teacher import Teacher
from app.models.teacher_leave import TeacherLeave
from app.models.user import User
from app.schemas.principal_report import (
    PrincipalReportOverviewResponse,
    PrincipalReportDetailsResponse,
    ReportMetricSummary,
    ReportAmountSummary,
    AttendanceBySubjectItem,
    FeesByStudentItem,
    ResultsBySubjectItem,
    TeacherAttendanceItem,
)
from app.services.academic_year import get_active_year
from app.utils.enums import AttendanceStatus, LeaveStatus


class PrincipalReportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _to_float(value: Optional[Union[Decimal, float, int]]) -> float:
        if value is None:
            return 0.0
        return float(value)

    async def _resolve_academic_year(
        self,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
    ) -> uuid.UUID:
        if academic_year_id is not None:
            return academic_year_id
        return (await get_active_year(school_id, self.db)).id

    async def overview(
        self,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID],
        report_date: date,
    ) -> PrincipalReportOverviewResponse:
        details = await self.details(
            current_user=current_user,
            academic_year_id=academic_year_id,
            report_date=report_date,
            metric=None,
            student_id=None,
            standard_id=None,
            section=None,
            teacher_id=None,
            subject_id=None,
        )
        return PrincipalReportOverviewResponse(
            academic_year_id=details.academic_year_id,
            report_date=details.report_date,
            student_attendance_percentage=details.student_attendance.value,
            student_present_count=details.student_attendance.numerator,
            student_total_records=details.student_attendance.denominator,
            fees_paid_amount=details.fees_paid.amount,
            fees_paid_transactions=details.fees_paid.count,
            results_average_percentage=details.results.value,
            students_with_results=details.results.numerator,
            result_entries_count=details.results.denominator,
            teacher_attendance_percentage=details.teacher_attendance.value,
            total_teachers=details.teacher_attendance.denominator,
            teachers_present_today=details.teacher_attendance.numerator,
            teachers_on_leave_today=sum(
                1 for item in details.teacher_attendance_items if item.on_leave
            ),
        )

    async def details(
        self,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID],
        report_date: date,
        metric: Optional[str],
        student_id: Optional[uuid.UUID],
        standard_id: Optional[uuid.UUID],
        section: Optional[str],
        teacher_id: Optional[uuid.UUID],
        subject_id: Optional[uuid.UUID],
    ) -> PrincipalReportDetailsResponse:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        resolved_year_id = await self._resolve_academic_year(school_id, academic_year_id)
        section_value = section.strip() if section else None

        # ── Student attendance summary + subject breakdown ─────────────────
        attendance_where = [
            Student.school_id == school_id,
            Attendance.academic_year_id == resolved_year_id,
        ]
        if student_id is not None:
            attendance_where.append(Attendance.student_id == student_id)
        if standard_id is not None:
            attendance_where.append(Student.standard_id == standard_id)
        if section_value:
            attendance_where.append(Student.section == section_value)
        if teacher_id is not None:
            attendance_where.append(Attendance.teacher_id == teacher_id)
        if subject_id is not None:
            attendance_where.append(Attendance.subject_id == subject_id)

        attendance_stmt = (
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (Attendance.status == AttendanceStatus.PRESENT, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("present"),
                func.coalesce(func.count(Attendance.id), 0).label("total"),
            )
            .select_from(Attendance)
            .join(Student, Student.id == Attendance.student_id)
            .where(*attendance_where)
        )
        attendance_row = (await self.db.execute(attendance_stmt)).one()
        student_present_count = int(attendance_row.present or 0)
        student_total_records = int(attendance_row.total or 0)
        student_attendance_percentage = (
            round((student_present_count / student_total_records) * 100, 2)
            if student_total_records > 0
            else 0.0
        )

        attendance_subject_stmt = (
            select(
                Attendance.subject_id,
                Subject.name.label("subject_name"),
                func.coalesce(
                    func.sum(
                        case((Attendance.status == AttendanceStatus.PRESENT, 1), else_=0)
                    ),
                    0,
                ).label("present"),
                func.coalesce(func.count(Attendance.id), 0).label("total"),
            )
            .select_from(Attendance)
            .join(Student, Student.id == Attendance.student_id)
            .join(Subject, Subject.id == Attendance.subject_id)
            .where(*attendance_where)
            .group_by(Attendance.subject_id, Subject.name)
            .order_by(Subject.name.asc())
        )
        attendance_subject_rows = (await self.db.execute(attendance_subject_stmt)).all()
        attendance_by_subject: List[AttendanceBySubjectItem] = []
        for row in attendance_subject_rows:
            present = int(row.present or 0)
            total = int(row.total or 0)
            pct = round((present / total) * 100, 2) if total > 0 else 0.0
            attendance_by_subject.append(
                AttendanceBySubjectItem(
                    subject_id=row.subject_id,
                    subject_name=row.subject_name,
                    present=present,
                    total=total,
                    percentage=pct,
                )
            )

        # ── Fees paid summary + student breakdown ──────────────────────────
        fees_where = [
            Payment.school_id == school_id,
            FeeStructure.academic_year_id == resolved_year_id,
            Student.school_id == school_id,
        ]
        if student_id is not None:
            fees_where.append(Payment.student_id == student_id)
        if standard_id is not None:
            fees_where.append(Student.standard_id == standard_id)
        if section_value:
            fees_where.append(Student.section == section_value)

        fees_stmt = (
            select(
                func.coalesce(func.sum(Payment.amount), 0).label("amount_paid"),
                func.coalesce(func.count(Payment.id), 0).label("transactions"),
            )
            .select_from(Payment)
            .join(FeeLedger, FeeLedger.id == Payment.fee_ledger_id)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == Payment.student_id)
            .where(*fees_where)
        )
        fees_row = (await self.db.execute(fees_stmt)).one()
        fees_paid_amount = round(self._to_float(fees_row.amount_paid), 2)
        fees_paid_transactions = int(fees_row.transactions or 0)

        fees_student_stmt = (
            select(
                Payment.student_id,
                Student.admission_number,
                func.coalesce(func.sum(Payment.amount), 0).label("paid_amount"),
                func.coalesce(func.count(Payment.id), 0).label("transactions"),
            )
            .select_from(Payment)
            .join(FeeLedger, FeeLedger.id == Payment.fee_ledger_id)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == Payment.student_id)
            .where(*fees_where)
            .group_by(Payment.student_id, Student.admission_number)
            .order_by(func.sum(Payment.amount).desc(), Student.admission_number.asc())
        )
        fees_student_rows = (await self.db.execute(fees_student_stmt)).all()
        fees_by_student: List[FeesByStudentItem] = [
            FeesByStudentItem(
                student_id=row.student_id,
                admission_number=row.admission_number,
                paid_amount=round(self._to_float(row.paid_amount), 2),
                transactions=int(row.transactions or 0),
            )
            for row in fees_student_rows
        ]

        # ── Results summary + subject breakdown ─────────────────────────────
        results_where = [
            Result.school_id == school_id,
            Result.is_published.is_(True),
            Exam.academic_year_id == resolved_year_id,
            Student.school_id == school_id,
        ]
        if student_id is not None:
            results_where.append(Result.student_id == student_id)
        if standard_id is not None:
            results_where.append(Student.standard_id == standard_id)
        if section_value:
            results_where.append(Student.section == section_value)
        if subject_id is not None:
            results_where.append(Result.subject_id == subject_id)

        results_stmt = (
            select(
                func.coalesce(func.avg(Result.percentage), 0).label("avg_pct"),
                func.coalesce(func.count(Result.id), 0).label("entries"),
                func.coalesce(func.count(distinct(Result.student_id)), 0).label("students"),
            )
            .select_from(Result)
            .join(Exam, Exam.id == Result.exam_id)
            .join(Student, Student.id == Result.student_id)
            .where(*results_where)
        )
        results_row = (await self.db.execute(results_stmt)).one()
        results_average_percentage = round(self._to_float(results_row.avg_pct), 2)
        result_entries_count = int(results_row.entries or 0)
        students_with_results = int(results_row.students or 0)

        results_subject_stmt = (
            select(
                Result.subject_id,
                Subject.name.label("subject_name"),
                func.coalesce(func.avg(Result.percentage), 0).label("avg_pct"),
                func.coalesce(func.count(Result.id), 0).label("entries"),
            )
            .select_from(Result)
            .join(Exam, Exam.id == Result.exam_id)
            .join(Student, Student.id == Result.student_id)
            .join(Subject, Subject.id == Result.subject_id)
            .where(*results_where)
            .group_by(Result.subject_id, Subject.name)
            .order_by(Subject.name.asc())
        )
        results_subject_rows = (await self.db.execute(results_subject_stmt)).all()
        results_by_subject: List[ResultsBySubjectItem] = [
            ResultsBySubjectItem(
                subject_id=row.subject_id,
                subject_name=row.subject_name,
                average_percentage=round(self._to_float(row.avg_pct), 2),
                entries=int(row.entries or 0),
            )
            for row in results_subject_rows
        ]

        # ── Teacher attendance (filter-aware) ───────────────────────────────
        teacher_pool_stmt = (
            select(
                Teacher.id.label("teacher_id"),
                Teacher.employee_code.label("employee_code"),
                User.email.label("email"),
                User.phone.label("phone"),
            )
            .select_from(Teacher)
            .join(User, User.id == Teacher.user_id)
            .where(
                Teacher.school_id == school_id,
                User.is_active.is_(True),
                or_(
                    Teacher.academic_year_id == resolved_year_id,
                    Teacher.academic_year_id.is_(None),
                ),
            )
        )
        if teacher_id is not None:
            teacher_pool_stmt = teacher_pool_stmt.where(Teacher.id == teacher_id)

        if standard_id is not None or section_value or subject_id is not None:
            teacher_scope_subq = (
                select(distinct(Attendance.teacher_id))
                .select_from(Attendance)
                .join(Student, Student.id == Attendance.student_id)
                .where(
                    Student.school_id == school_id,
                    Attendance.academic_year_id == resolved_year_id,
                )
            )
            if standard_id is not None:
                teacher_scope_subq = teacher_scope_subq.where(Student.standard_id == standard_id)
            if section_value:
                teacher_scope_subq = teacher_scope_subq.where(Student.section == section_value)
            if subject_id is not None:
                teacher_scope_subq = teacher_scope_subq.where(Attendance.subject_id == subject_id)
            if student_id is not None:
                teacher_scope_subq = teacher_scope_subq.where(Attendance.student_id == student_id)
            teacher_pool_stmt = teacher_pool_stmt.where(Teacher.id.in_(teacher_scope_subq))

        teacher_rows = (await self.db.execute(teacher_pool_stmt)).all()
        teacher_ids = [row.teacher_id for row in teacher_rows]

        present_teacher_ids: Set[uuid.UUID] = set()
        leave_teacher_ids: Set[uuid.UUID] = set()

        if teacher_ids:
            present_stmt = (
                select(distinct(Attendance.teacher_id))
                .select_from(Attendance)
                .join(Student, Student.id == Attendance.student_id)
                .where(
                    Student.school_id == school_id,
                    Attendance.academic_year_id == resolved_year_id,
                    Attendance.date == report_date,
                    Attendance.teacher_id.in_(teacher_ids),
                )
            )
            if standard_id is not None:
                present_stmt = present_stmt.where(Student.standard_id == standard_id)
            if section_value:
                present_stmt = present_stmt.where(Student.section == section_value)
            if subject_id is not None:
                present_stmt = present_stmt.where(Attendance.subject_id == subject_id)
            if student_id is not None:
                present_stmt = present_stmt.where(Attendance.student_id == student_id)
            present_teacher_ids = {
                row[0] for row in (await self.db.execute(present_stmt)).all()
            }

            leave_stmt = (
                select(distinct(TeacherLeave.teacher_id))
                .select_from(TeacherLeave)
                .where(
                    TeacherLeave.school_id == school_id,
                    TeacherLeave.academic_year_id == resolved_year_id,
                    TeacherLeave.status == LeaveStatus.APPROVED,
                    TeacherLeave.teacher_id.in_(teacher_ids),
                    and_(
                        TeacherLeave.from_date <= report_date,
                        TeacherLeave.to_date >= report_date,
                    ),
                )
            )
            leave_teacher_ids = {
                row[0] for row in (await self.db.execute(leave_stmt)).all()
            }

        teacher_items: List[TeacherAttendanceItem] = []
        for row in teacher_rows:
            label = row.employee_code
            if row.email:
                label = row.email.split("@")[0]
            elif row.phone:
                label = row.phone

            on_leave = row.teacher_id in leave_teacher_ids
            is_present = row.teacher_id in present_teacher_ids and not on_leave
            teacher_items.append(
                TeacherAttendanceItem(
                    teacher_id=row.teacher_id,
                    teacher_label=label,
                    is_present=is_present,
                    on_leave=on_leave,
                )
            )

        total_teachers = len(teacher_items)
        teachers_present_today = sum(1 for item in teacher_items if item.is_present)
        teacher_attendance_percentage = (
            round((teachers_present_today / total_teachers) * 100, 2)
            if total_teachers > 0
            else 0.0
        )

        return PrincipalReportDetailsResponse(
            academic_year_id=resolved_year_id,
            report_date=report_date,
            metric=metric,
            filters={
                "student_id": str(student_id) if student_id else None,
                "standard_id": str(standard_id) if standard_id else None,
                "section": section_value,
                "teacher_id": str(teacher_id) if teacher_id else None,
                "subject_id": str(subject_id) if subject_id else None,
            },
            student_attendance=ReportMetricSummary(
                value=student_attendance_percentage,
                numerator=student_present_count,
                denominator=student_total_records,
            ),
            fees_paid=ReportAmountSummary(
                amount=fees_paid_amount,
                count=fees_paid_transactions,
            ),
            results=ReportMetricSummary(
                value=results_average_percentage,
                numerator=students_with_results,
                denominator=result_entries_count,
            ),
            teacher_attendance=ReportMetricSummary(
                value=teacher_attendance_percentage,
                numerator=teachers_present_today,
                denominator=total_teachers,
            ),
            attendance_by_subject=attendance_by_subject,
            fees_by_student=fees_by_student,
            results_by_subject=results_by_subject,
            teacher_attendance_items=teacher_items,
        )

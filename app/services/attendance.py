import uuid
from datetime import date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import BackgroundTasks

from app.repositories.attendance import AttendanceRepository
from app.repositories.teacher import TeacherRepository
from app.repositories.student import StudentRepository
from app.schemas.attendance import (
    MarkAttendanceRequest,
    MarkAttendanceResponse,
    StudentAttendanceAnalytics,
    SubjectAttendanceStat,
    BelowThresholdResponse,
    BelowThresholdStudent,
    LectureAttendanceResponse,
    LectureStudentEntry,
    StudentDetailAttendanceResponse,
    MonthlyAttendanceSummary,
    AttendanceDashboardResponse,
    ClassAttendanceStat,
    SubjectSchoolAttendanceStat,
    AbsenteeEntry,
    AttendanceTrendItem,
)
from app.services.teacher_class_subject import TeacherClassSubjectService
from app.services.notification import NotificationService
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)
from app.core.dependencies import CurrentUser
from app.utils.enums import RoleEnum, AttendanceStatus, NotificationType, NotificationPriority


class AttendanceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AttendanceRepository(db)
        self.teacher_repo = TeacherRepository(db)
        self.student_repo = StudentRepository(db)
        self.tcs_service = TeacherClassSubjectService(db)
        self.notif_service = NotificationService(db)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_teacher_for_user(self, current_user: CurrentUser):
        teacher = await self.teacher_repo.get_by_user_id(current_user.id)
        if not teacher:
            raise NotFoundException(detail="Teacher profile not found for this user")
        return teacher

    async def _assert_teacher_can_view_student(
        self,
        current_user: CurrentUser,
        student,
    ) -> None:
        teacher = await self._get_teacher_for_user(current_user)
        assignments, _ = await self.tcs_service.repo.list_by_teacher(
            teacher_id=teacher.id,
            academic_year_id=student.academic_year_id,
        )
        for a in assignments:
            if a.standard_id == student.standard_id and a.section == (student.section or ""):
                return
        raise ForbiddenException(detail="You are not assigned to this student's class/section")

    def _require_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    # ── Mark Attendance ───────────────────────────────────────────────────────

    async def mark_attendance(
        self,
        payload: MarkAttendanceRequest,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> MarkAttendanceResponse:
        school_id = self._require_school(current_user)

        teacher = await self._get_teacher_for_user(current_user)

        # 1. Assert teacher owns this class-subject
        await self.tcs_service.assert_teacher_owns_class_subject(
            teacher_id=teacher.id,
            standard_id=payload.standard_id,
            subject_id=payload.subject_id,
            academic_year_id=payload.academic_year_id,
            section=payload.section,
        )

        # 2. Validate all students belong to the class/section/year in this school
        for record in payload.records:
            student = await self.student_repo.get_by_id(record.student_id, school_id)
            if not student:
                raise NotFoundException(
                    detail=f"Student {record.student_id} not found in this school"
                )
            if student.standard_id != payload.standard_id:
                raise ValidationException(
                    detail=f"Student {student.admission_number} does not belong to selected class"
                )
            if (student.section or "") != payload.section:
                raise ValidationException(
                    detail=f"Student {student.admission_number} does not belong to selected section"
                )
            if student.academic_year_id != payload.academic_year_id:
                raise ValidationException(
                    detail=f"Student {student.admission_number} is not in selected academic year"
                )

        # 3. Build upsert records
        records = [
            {
                "student_id": r.student_id,
                "teacher_id": teacher.id,
                "standard_id": payload.standard_id,
                "section": payload.section,
                "subject_id": payload.subject_id,
                "academic_year_id": payload.academic_year_id,
                # Date-based attendance model: one record per subject/date.
                "lecture_number": 1,
                "date": payload.date,
                "status": r.status,
            }
            for r in payload.records
        ]

        rowcount, _ = await self.repo.bulk_upsert(records)
        # Intentional: _notify_attendance_updates uses its own session and reads these rows.
        await self.db.commit()

        # 4. Background notifications for ABSENT / LATE students
        if payload.records:
            background_tasks.add_task(
                self._notify_attendance_updates,
                payload.records,
                school_id,
                payload.date,
            )

        return MarkAttendanceResponse(
            inserted=rowcount,
            updated=0,
            total=len(records),
            date=payload.date,
        )

    # ── Notification helper (runs in background — uses its own session) ───────

    async def _notify_attendance_updates(
        self,
        records,
        school_id: uuid.UUID,
        attendance_date: date,
    ) -> None:
        for row in records:
            try:
                student_id = row.student_id
                status = row.status
                student = await self.student_repo.get_by_id(student_id, school_id)
                if not student:
                    continue

                status_label = status.value.title()
                is_high = status in (AttendanceStatus.ABSENT, AttendanceStatus.LATE)
                priority = (
                    NotificationPriority.HIGH
                    if is_high
                    else NotificationPriority.MEDIUM
                )
                when_text = attendance_date.strftime("%d %b %Y")

                if student.parent and student.parent.user_id:
                    await self.notif_service.create(
                        user_id=student.parent.user_id,
                        title="Attendance Update",
                        body=(
                            f"Your child (Admission No: {student.admission_number}) "
                            f"was marked {status_label} on {when_text}."
                        ),
                        type=NotificationType.ATTENDANCE,
                        priority=priority,
                        reference_id=student_id,
                    )
                if student.user_id:
                    await self.notif_service.create(
                        user_id=student.user_id,
                        title="Attendance Marked",
                        body=(
                            f"You were marked {status_label} on {when_text}."
                        ),
                        type=NotificationType.ATTENDANCE,
                        priority=priority,
                        reference_id=student_id,
                    )
            except Exception:
                pass

    # ── List Attendance (existing, preserved) ─────────────────────────────────

    async def list_attendance(
        self,
        current_user: CurrentUser,
        student_id: Optional[uuid.UUID],
        standard_id: Optional[uuid.UUID],
        section: Optional[str],
        academic_year_id: Optional[uuid.UUID],
        record_date: Optional[date],
        month: Optional[int],
        year: Optional[int],
        subject_id: Optional[uuid.UUID],
    ):
        school_id = self._require_school(current_user)

        # Student history flow for all roles
        if student_id:
            s = await self.student_repo.get_by_id(student_id, school_id)
            if not s:
                raise NotFoundException(detail="Student not found")

            if current_user.role == RoleEnum.PARENT:
                if s.parent_id != current_user.parent_id:
                    raise ForbiddenException(detail="Not your child")
            elif current_user.role == RoleEnum.STUDENT:
                if s.user_id != current_user.id:
                    raise ForbiddenException(detail="You can only view your own attendance")
            elif current_user.role == RoleEnum.TEACHER:
                await self._assert_teacher_can_view_student(current_user, s)

            items, total = await self.repo.list_by_student(
                student_id=student_id,
                school_id=school_id,
                month=month,
                year=year,
                subject_id=subject_id,
            )
            return {"items": items, "total": total}

        # Teacher / Principal: class snapshot view
        if not standard_id or not section or not record_date:
            raise ValidationException(
                "standard_id, section and date are required for class attendance view"
            )
        if current_user.role == RoleEnum.TEACHER:
            teacher = await self._get_teacher_for_user(current_user)
            if not subject_id:
                raise ValidationException(
                    "subject_id is required for teacher class attendance view"
                )
            if not academic_year_id:
                raise ValidationException(
                    "academic_year_id is required for teacher class attendance view"
                )
            await self.tcs_service.assert_teacher_owns_class_subject(
                teacher_id=teacher.id,
                standard_id=standard_id,
                subject_id=subject_id,
                academic_year_id=academic_year_id,
                section=section,
            )
        items = await self.repo.list_by_class_date(
            standard_id=standard_id,
            section=section,
            school_id=school_id,
            record_date=record_date,
            academic_year_id=academic_year_id,
            subject_id=subject_id,
        )
        return {"items": items, "total": len(items)}

    # ── Lecture-wise snapshot ─────────────────────────────────────────────────

    async def get_lecture_attendance(
        self,
        standard_id: uuid.UUID,
        section: str,
        subject_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        record_date: date,
        current_user: CurrentUser,
    ) -> LectureAttendanceResponse:
        school_id = self._require_school(current_user)

        # TEACHER: must own this class-subject
        if current_user.role == RoleEnum.TEACHER:
            teacher = await self._get_teacher_for_user(current_user)
            await self.tcs_service.assert_teacher_owns_class_subject(
                teacher_id=teacher.id,
                standard_id=standard_id,
                subject_id=subject_id,
                academic_year_id=academic_year_id,
                section=section,
            )
        elif current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT):
            raise ForbiddenException(detail="Not authorized to view class lecture snapshots")

        rows = await self.repo.get_lecture_snapshot(
            standard_id=standard_id,
            section=section,
            subject_id=subject_id,
            academic_year_id=academic_year_id,
            school_id=school_id,
            record_date=record_date,
        )

        entries: list[LectureStudentEntry] = []
        present_count = 0
        absent_count = 0
        late_count = 0

        for row in rows:
            raw_status = row.get("status")
            # Unmarked students default to ABSENT for display purposes
            status = AttendanceStatus(raw_status) if raw_status else AttendanceStatus.ABSENT
            entries.append(
                LectureStudentEntry(
                    student_id=row["student_id"],
                    admission_number=row["admission_number"],
                    student_name=row.get("student_name"),
                    roll_number=row.get("roll_number"),
                    status=status,
                    attendance_id=row.get("attendance_id"),
                )
            )
            if status == AttendanceStatus.PRESENT:
                present_count += 1
            elif status == AttendanceStatus.ABSENT:
                absent_count += 1
            elif status == AttendanceStatus.LATE:
                late_count += 1

        return LectureAttendanceResponse(
            standard_id=standard_id,
            section=section,
            subject_id=subject_id,
            academic_year_id=academic_year_id,
            date=record_date,
            total_students=len(entries),
            present_count=present_count,
            absent_count=absent_count,
            late_count=late_count,
            entries=entries,
        )

    # ── Student detail attendance ─────────────────────────────────────────────

    async def get_student_detail_attendance(
        self,
        student_id: uuid.UUID,
        current_user: CurrentUser,
        year: Optional[int] = None,
    ) -> StudentDetailAttendanceResponse:
        school_id = self._require_school(current_user)

        student = await self.student_repo.get_by_id(student_id, school_id)
        if not student:
            raise NotFoundException(detail="Student not found")

        # RBAC gate
        if current_user.role == RoleEnum.PARENT:
            if student.parent_id != current_user.parent_id:
                raise ForbiddenException(detail="Not your child")
        elif current_user.role == RoleEnum.STUDENT:
            if student.user_id != current_user.id:
                raise ForbiddenException(detail="You can only view your own attendance")
        elif current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_can_view_student(current_user, student)
        # PRINCIPAL / TRUSTEE: unrestricted

        # Lecture-wise raw records
        lecture_items, _ = await self.repo.list_by_student(
            student_id=student_id,
            school_id=school_id,
            year=year,
        )

        # Subject-wise stats
        subject_rows = await self.repo.get_student_subject_stats(
            student_id=student_id,
            school_id=school_id,
            year=year,
        )
        subject_stats: list[SubjectAttendanceStat] = []
        total_classes = 0
        total_present = 0
        for row in subject_rows:
            pct = (
                round((row["present"] / row["total"]) * 100, 2)
                if row["total"] > 0
                else 0.0
            )
            subject_stats.append(
                SubjectAttendanceStat(
                    subject_id=row["subject_id"],
                    subject_name=row["subject_name"],
                    subject_code=row["subject_code"],
                    total_classes=row["total"],
                    present=row["present"],
                    absent=row["absent"],
                    late=row["late"],
                    percentage=pct,
                )
            )
            total_classes += row["total"]
            total_present += row["present"]

        overall = (
            round((total_present / total_classes) * 100, 2)
            if total_classes > 0
            else 0.0
        )

        # Monthly summary
        monthly_rows = await self.repo.get_student_monthly_summary(
            student_id=student_id,
            school_id=school_id,
            year=year,
        )
        monthly_summary: list[MonthlyAttendanceSummary] = []
        for row in monthly_rows:
            total = row["total"] or 0
            present = row["present"] or 0
            pct = round((present / total) * 100, 2) if total > 0 else 0.0
            monthly_summary.append(
                MonthlyAttendanceSummary(
                    month=int(row["month"]),
                    year=int(row["year"]),
                    total_classes=total,
                    present=present,
                    absent=row["absent"] or 0,
                    late=row["late"] or 0,
                    percentage=pct,
                )
            )

        # Resolve student display name
        student_name: Optional[str] = getattr(student, "student_name", None)

        return StudentDetailAttendanceResponse(
            student_id=student_id,
            admission_number=student.admission_number,
            student_name=student_name,
            overall_percentage=overall,
            lecture_records=lecture_items,
            subject_stats=subject_stats,
            monthly_summary=monthly_summary,
        )

    # ── Student analytics (existing, preserved) ───────────────────────────────

    async def student_analytics(
        self,
        student_id: uuid.UUID,
        current_user: CurrentUser,
        month: Optional[int],
        year: Optional[int],
    ) -> StudentAttendanceAnalytics:
        school_id = self._require_school(current_user)

        student = await self.student_repo.get_by_id(student_id, school_id)
        if not student:
            raise NotFoundException(detail="Student not found")

        if current_user.role == RoleEnum.PARENT:
            if student.parent_id != current_user.parent_id:
                raise ForbiddenException(detail="Not your child")
        elif current_user.role == RoleEnum.STUDENT:
            if student.user_id != current_user.id:
                raise ForbiddenException(detail="You can only view your own attendance")
        elif current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_can_view_student(current_user, student)

        stats = await self.repo.get_student_subject_stats(
            student_id=student_id,
            school_id=school_id,
            month=month,
            year=year,
        )

        subject_stats: list[SubjectAttendanceStat] = []
        total_classes = 0
        total_present = 0

        for row in stats:
            pct = (
                round((row["present"] / row["total"]) * 100, 2)
                if row["total"] > 0
                else 0.0
            )
            subject_stats.append(
                SubjectAttendanceStat(
                    subject_id=row["subject_id"],
                    subject_name=row["subject_name"],
                    subject_code=row["subject_code"],
                    total_classes=row["total"],
                    present=row["present"],
                    absent=row["absent"],
                    late=row["late"],
                    percentage=pct,
                )
            )
            total_classes += row["total"]
            total_present += row["present"]

        overall = (
            round((total_present / total_classes) * 100, 2)
            if total_classes > 0
            else 0.0
        )

        return StudentAttendanceAnalytics(
            student_id=student_id,
            month=month,
            year=year,
            overall_percentage=overall,
            subjects=subject_stats,
        )

    # ── Below threshold (existing, preserved) ─────────────────────────────────

    async def below_threshold(
        self,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        current_user: CurrentUser,
        threshold: float = 75.0,
    ) -> BelowThresholdResponse:
        school_id = self._require_school(current_user)

        rows = await self.repo.get_students_below_threshold(
            standard_id=standard_id,
            school_id=school_id,
            academic_year_id=academic_year_id,
            threshold=threshold,
        )

        students = [
            BelowThresholdStudent(
                student_id=r["student_id"],
                admission_number=r["admission_number"],
                section=r["section"] or "",
                overall_percentage=round(float(r["percentage"] or 0), 2),
            )
            for r in rows
        ]

        return BelowThresholdResponse(
            standard_id=standard_id,
            threshold=threshold,
            academic_year_id=academic_year_id,
            students=students,
            total=len(students),
        )

    # ── Analytics Dashboard (Principal / Trustee) ─────────────────────────────

    async def get_analytics_dashboard(
        self,
        academic_year_id: uuid.UUID,
        current_user: CurrentUser,
        standard_id: Optional[uuid.UUID] = None,
        top_absentees_limit: int = 10,
        trend_weeks: int = 8,
        trend_months: int = 6,
    ) -> AttendanceDashboardResponse:
        school_id = self._require_school(current_user)

        # RBAC: only Principal and Trustee
        if current_user.role not in (
            RoleEnum.PRINCIPAL, RoleEnum.TRUSTEE,
        ):
            raise ForbiddenException(
                detail="Only Principal and Trustee can access the analytics dashboard"
            )

        # 1. School-wide totals
        totals = await self.repo.get_school_totals(
            school_id=school_id,
            academic_year_id=academic_year_id,
        )
        total_records = int(totals["total"] or 0)
        present = int(totals["present"] or 0)
        absent = int(totals["absent"] or 0)
        late = int(totals["late"] or 0)
        overall_pct = (
            round((present / total_records) * 100, 2) if total_records > 0 else 0.0
        )

        # 2. Class-wise stats
        class_rows = await self.repo.get_class_analytics(
            school_id=school_id,
            academic_year_id=academic_year_id,
            standard_id=standard_id,
        )
        class_stats: list[ClassAttendanceStat] = []
        for row in class_rows:
            tot = int(row["total_records"] or 0)
            pre = int(row["present"] or 0)
            pct = round((pre / tot) * 100, 2) if tot > 0 else 0.0
            class_stats.append(
                ClassAttendanceStat(
                    standard_id=row["standard_id"],
                    standard_name=row["standard_name"],
                    section=row["section"],
                    total_records=tot,
                    present=pre,
                    absent=int(row["absent"] or 0),
                    late=int(row["late"] or 0),
                    percentage=pct,
                )
            )

        # 3. Subject-wise stats (school-wide)
        subject_rows = await self.repo.get_school_subject_analytics(
            school_id=school_id,
            academic_year_id=academic_year_id,
        )
        subject_stats: list[SubjectSchoolAttendanceStat] = []
        for row in subject_rows:
            tot = int(row["total_records"] or 0)
            pre = int(row["present"] or 0)
            pct = round((pre / tot) * 100, 2) if tot > 0 else 0.0
            subject_stats.append(
                SubjectSchoolAttendanceStat(
                    subject_id=row["subject_id"],
                    subject_name=row["subject_name"],
                    subject_code=row["subject_code"],
                    total_records=tot,
                    present=pre,
                    absent=int(row["absent"] or 0),
                    late=int(row["late"] or 0),
                    percentage=pct,
                )
            )

        # 4. Top absentees
        absentee_rows = await self.repo.get_top_absentees(
            school_id=school_id,
            academic_year_id=academic_year_id,
            limit=top_absentees_limit,
            standard_id=standard_id,
        )
        top_absentees: list[AbsenteeEntry] = []
        for row in absentee_rows:
            tot = int(row["total_classes"] or 0)
            abs_count = int(row["absences"] or 0)
            pre_count = int(row["present_count"] or 0)
            pct = round((pre_count / tot) * 100, 2) if tot > 0 else 0.0
            top_absentees.append(
                AbsenteeEntry(
                    student_id=row["student_id"],
                    admission_number=row["admission_number"],
                    student_name=row.get("student_name") or None,
                    standard_id=row["standard_id"],
                    standard_name=row["standard_name"],
                    section=row["section"] or "",
                    total_classes=tot,
                    absences=abs_count,
                    percentage=pct,
                )
            )

        # 5. Weekly trend
        weekly_rows = await self.repo.get_weekly_trend(
            school_id=school_id,
            academic_year_id=academic_year_id,
            weeks=trend_weeks,
        )
        weekly_trend: list[AttendanceTrendItem] = []
        for row in weekly_rows:
            tot = int(row["total_records"] or 0)
            pre = int(row["present"] or 0)
            pct = round((pre / tot) * 100, 2) if tot > 0 else 0.0
            weekly_trend.append(
                AttendanceTrendItem(
                    period_label=row["period_label"],
                    period_year=int(row["period_year"]),
                    period_value=int(row["period_value"]),
                    total_records=tot,
                    present=pre,
                    absent=int(row["absent"] or 0),
                    late=int(row["late"] or 0),
                    percentage=pct,
                )
            )

        # 6. Monthly trend
        monthly_rows = await self.repo.get_monthly_trend(
            school_id=school_id,
            academic_year_id=academic_year_id,
            months=trend_months,
        )
        monthly_trend: list[AttendanceTrendItem] = []
        for row in monthly_rows:
            tot = int(row["total_records"] or 0)
            pre = int(row["present"] or 0)
            pct = round((pre / tot) * 100, 2) if tot > 0 else 0.0
            monthly_trend.append(
                AttendanceTrendItem(
                    period_label=row["period_label"],
                    period_year=int(row["period_year"]),
                    period_value=int(row["period_value"]),
                    total_records=tot,
                    present=pre,
                    absent=int(row["absent"] or 0),
                    late=int(row["late"] or 0),
                    percentage=pct,
                )
            )

        return AttendanceDashboardResponse(
            school_id=school_id,
            academic_year_id=academic_year_id,
            overall_percentage=overall_pct,
            total_records=total_records,
            present=present,
            absent=absent,
            late=late,
            class_stats=class_stats,
            subject_stats=subject_stats,
            top_absentees=top_absentees,
            weekly_trend=weekly_trend,
            monthly_trend=monthly_trend,
        )
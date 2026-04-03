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
    ClassAttendanceSnapshot,
    ClassSnapshotRecord,
    BelowThresholdResponse,
    BelowThresholdStudent,
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

    async def _get_teacher_for_user(self, current_user: CurrentUser):
        teacher = await self.teacher_repo.get_by_user_id(current_user.id)
        if not teacher:
            raise NotFoundException(detail="Teacher profile not found for this user")
        return teacher

    async def mark_attendance(
        self,
        payload: MarkAttendanceRequest,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> MarkAttendanceResponse:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        teacher = await self._get_teacher_for_user(current_user)

        # 1. Assert teacher owns this class-subject
        await self.tcs_service.assert_teacher_owns_class_subject(
            teacher_id=teacher.id,
            standard_id=payload.standard_id,
            subject_id=payload.subject_id,
            academic_year_id=payload.academic_year_id,
            section=payload.section,
        )

        # 1b. Validate all students belong to class/section/year in this school
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

        # 2. Build upsert records
        records = [
            {
                "student_id": r.student_id,
                "teacher_id": teacher.id,
                "standard_id": payload.standard_id,
                "section": payload.section,
                "subject_id": payload.subject_id,
                "academic_year_id": payload.academic_year_id,
                "lecture_number": payload.lecture_number,
                "date": payload.date,
                "status": r.status,
            }
            for r in payload.records
        ]

        rowcount, _ = await self.repo.bulk_upsert(records)
        await self.db.commit()

        # 3. Background notifications for ABSENT students
        if payload.records:
            background_tasks.add_task(
                self._notify_attendance_updates,
                payload.records,
                school_id,
                payload.date,
                payload.lecture_number,
            )

        return MarkAttendanceResponse(
            inserted=rowcount,
            updated=0,
            total=len(records),
            date=payload.date,
            lecture_number=payload.lecture_number,
        )

    async def _notify_attendance_updates(
        self,
        records,
        school_id: uuid.UUID,
        attendance_date: date,
        lecture_number: int,
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
                when_text = (
                    f"{attendance_date.strftime('%d %b %Y')} • Lecture {lecture_number}"
                )

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
        lecture_number: Optional[int],
    ):
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

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
                lecture_number=lecture_number,
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
            lecture_number=lecture_number,
        )
        return {"items": items, "total": len(items)}

    # ── Analytics ─────────────────────────────────────────────────────────────

    async def student_analytics(
        self,
        student_id: uuid.UUID,
        current_user: CurrentUser,
        month: Optional[int],
        year: Optional[int],
    ) -> StudentAttendanceAnalytics:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        student = await self.student_repo.get_by_id(student_id, school_id)
        if not student:
            raise NotFoundException(detail="Student not found")

        if current_user.role == RoleEnum.PARENT:
            if student.parent_id != current_user.parent_id:
                raise ForbiddenException(detail="Not your child")

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

    async def class_snapshot(
        self,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        record_date: date,
        current_user: CurrentUser,
        section: Optional[str] = None,
        subject_id: Optional[uuid.UUID] = None,
        lecture_number: Optional[int] = None,
    ) -> ClassAttendanceSnapshot:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        rows = await self.repo.get_class_snapshot(
            standard_id=standard_id,
            section=section,
            school_id=school_id,
            record_date=record_date,
            academic_year_id=academic_year_id,
            subject_id=subject_id,
            lecture_number=lecture_number,
        )

        records = [ClassSnapshotRecord(**r) for r in rows]
        present = sum(1 for r in records if r.status == AttendanceStatus.PRESENT)
        absent = sum(1 for r in records if r.status == AttendanceStatus.ABSENT)
        late = sum(1 for r in records if r.status == AttendanceStatus.LATE)
        not_marked = sum(1 for r in records if r.status is None)

        return ClassAttendanceSnapshot(
            standard_id=standard_id,
            date=record_date,
            total_students=len(records),
            present=present,
            absent=absent,
            late=late,
            not_marked=not_marked,
            records=records,
        )

    async def below_threshold(
        self,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        current_user: CurrentUser,
        threshold: float = 75.0,
    ) -> BelowThresholdResponse:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

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

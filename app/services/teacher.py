import uuid
from typing import Optional
from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.attendance import Attendance
from app.models.exam import Exam
from app.models.masters import Standard, Subject
from app.models.result import Result
from app.models.student import Student
from app.models.submission import Submission
from app.repositories.teacher import TeacherRepository
from app.models.teacher_class_subject import TeacherClassSubject
from app.repositories.user import UserRepository
from app.schemas.teacher_analytics import (
    TeacherAnalyticsResponse,
    TeacherAssignmentAnalytics,
    TeacherAssignmentSubmissionAnalytics,
    TeacherAttendanceAnalytics,
    TeacherAttendanceBySubjectAnalytics,
    TeacherMarksAnalytics,
    TeacherMarksBySubjectAnalytics,
)
from app.schemas.teacher import TeacherCreate, TeacherUpdate
from app.models.teacher import Teacher
from app.core.security import hash_password
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ConflictException,
    ForbiddenException,
)
from app.core.dependencies import CurrentUser
from app.utils.enums import RoleEnum
from app.utils.enums import AttendanceStatus
from app.utils.date_utils import today_in_app_timezone


class TeacherService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.teacher_repo = TeacherRepository(db)
        self.user_repo = UserRepository(db)

    async def create_teacher(
        self,
        payload: TeacherCreate,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Teacher:
        # Guard: email uniqueness
        existing_email = await self.user_repo.get_by_email(payload.user.email)
        if existing_email:
            raise ConflictException(detail="A user with this email already exists")

        # Guard: phone uniqueness
        existing_phone = await self.user_repo.get_by_phone(payload.user.phone)
        if existing_phone:
            raise ConflictException(detail="A user with this phone number already exists")

        # Guard: employee_code uniqueness
        existing_code = await self.teacher_repo.get_by_employee_code(payload.employee_code)
        if existing_code:
            raise ConflictException(detail="A teacher with this employee code already exists")

        # 1. Create users row (role=TEACHER)
        user = await self.user_repo.create(
            {
                "email": payload.user.email.lower().strip(),
                "phone": payload.user.phone,
                "hashed_password": hash_password(payload.user.password),
                "role": RoleEnum.TEACHER,
                "school_id": school_id,
                "is_active": True,
            }
        )

        # 2. Create teachers row linked to that user
        teacher = await self.teacher_repo.create(
            {
                "user_id": user.id,
                "school_id": school_id,
                "employee_code": payload.employee_code,
                "join_date": payload.join_date,
                "specialization": payload.specialization,
                "academic_year_id": payload.academic_year_id,
            }
        )

        await self.db.commit()

        # Reload with user eager-loaded
        return await self.teacher_repo.get_by_id(teacher.id, school_id)  # type: ignore[return-value]

    async def get_teacher(
        self,
        teacher_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Teacher:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        teacher = await self.teacher_repo.get_by_id(teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Teacher not found")

        # A TEACHER may only view their own profile
        if current_user.role == RoleEnum.TEACHER:
            if teacher.user_id != current_user.id:
                raise ForbiddenException(detail="Access denied")

        return teacher

    async def list_teachers(
        self,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        standard_id: Optional[uuid.UUID],
        subject_id: Optional[uuid.UUID],
        subject_name: Optional[str],
        page: int,
        page_size: int,
    ) -> tuple[list[Teacher], int]:
        return await self.teacher_repo.list_by_school(
            school_id=school_id,
            academic_year_id=academic_year_id,
            standard_id=standard_id,
            subject_id=subject_id,
            subject_name=subject_name,
            page=page,
            page_size=page_size,
        )

    async def update_teacher(
        self,
        teacher_id: uuid.UUID,
        payload: TeacherUpdate,
        current_user: CurrentUser,
    ) -> Teacher:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        teacher = await self.teacher_repo.get_by_id(teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Teacher not found")

        update_data = payload.model_dump(exclude_unset=True)

        # Guard: employee_code uniqueness on update
        new_code = update_data.get("employee_code")
        if new_code and new_code != teacher.employee_code:
            existing_code = await self.teacher_repo.get_by_employee_code(new_code)
            if existing_code:
                raise ConflictException(
                    detail="A teacher with this employee code already exists"
                )

        updated = await self.teacher_repo.update(teacher, update_data)
        await self.db.commit()

        return await self.teacher_repo.get_by_id(teacher_id, school_id)  # type: ignore[return-value]

    async def get_my_analytics(
        self,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        subject_id: Optional[uuid.UUID] = None,
    ) -> TeacherAnalyticsResponse:
        if current_user.role != RoleEnum.TEACHER:
            raise ForbiddenException("Only teachers can access teacher analytics")
        if not current_user.school_id:
            raise ValidationException("school_id is required")

        school_id = current_user.school_id
        section_normalized = section.strip().upper() if section else None

        teacher_q = await self.db.execute(
            select(Teacher.id).where(
                and_(
                    Teacher.user_id == current_user.id,
                    Teacher.school_id == school_id,
                )
            )
        )
        teacher_id = teacher_q.scalar_one_or_none()
        if not teacher_id:
            raise ForbiddenException("Teacher profile not found for this user")

        assignment_scope_filters = [TeacherClassSubject.teacher_id == teacher_id]
        if academic_year_id is not None:
            assignment_scope_filters.append(
                TeacherClassSubject.academic_year_id == academic_year_id
            )
        if standard_id is not None:
            assignment_scope_filters.append(TeacherClassSubject.standard_id == standard_id)
        if section_normalized is not None:
            assignment_scope_filters.append(
                func.upper(func.trim(TeacherClassSubject.section)) == section_normalized
            )
        if subject_id is not None:
            assignment_scope_filters.append(TeacherClassSubject.subject_id == subject_id)

        assigned_q = await self.db.execute(
            select(
                TeacherClassSubject.standard_id,
                Standard.name.label("standard_name"),
                TeacherClassSubject.section,
                TeacherClassSubject.subject_id,
                Subject.name.label("subject_name"),
                TeacherClassSubject.academic_year_id,
            )
            .join(Standard, Standard.id == TeacherClassSubject.standard_id)
            .join(Subject, Subject.id == TeacherClassSubject.subject_id)
            .where(and_(*assignment_scope_filters))
            .order_by(
                Standard.level.asc(),
                Standard.name.asc(),
                func.upper(func.trim(TeacherClassSubject.section)).asc(),
                Subject.name.asc(),
            )
        )
        assignments = [
            TeacherAssignmentAnalytics(
                standard_id=row.standard_id,
                standard_name=row.standard_name,
                section=(row.section or "").strip().upper(),
                subject_id=row.subject_id,
                subject_name=row.subject_name,
                academic_year_id=row.academic_year_id,
            )
            for row in assigned_q.all()
        ]

        assignment_filters = [
            Assignment.teacher_id == teacher_id,
            Assignment.school_id == school_id,
        ]
        if academic_year_id is not None:
            assignment_filters.append(Assignment.academic_year_id == academic_year_id)
        if standard_id is not None:
            assignment_filters.append(Assignment.standard_id == standard_id)
        if subject_id is not None:
            assignment_filters.append(Assignment.subject_id == subject_id)
        if section_normalized is not None:
            section_exists = exists(
                select(TeacherClassSubject.id).where(
                    and_(
                        TeacherClassSubject.teacher_id == teacher_id,
                        TeacherClassSubject.standard_id == Assignment.standard_id,
                        TeacherClassSubject.subject_id == Assignment.subject_id,
                        TeacherClassSubject.academic_year_id == Assignment.academic_year_id,
                        func.upper(func.trim(TeacherClassSubject.section))
                        == section_normalized,
                    )
                )
            )
            assignment_filters.append(section_exists)

        assignment_id_rows = await self.db.execute(
            select(Assignment.id).where(and_(*assignment_filters))
        )
        assignment_ids = list(assignment_id_rows.scalars().all())
        total_assignments = len(assignment_ids)

        overdue_q = await self.db.execute(
            select(func.count(Assignment.id)).where(
                and_(
                    *assignment_filters,
                    Assignment.is_active.is_(True),
                    Assignment.due_date < today_in_app_timezone(),
                )
            )
        )
        overdue_assignments = int(overdue_q.scalar_one() or 0)

        total_submissions = 0
        late_submissions = 0
        on_time_submissions = 0
        pending_review_submissions = 0
        if assignment_ids:
            submission_q = await self.db.execute(
                select(
                    func.count(Submission.id).label("total"),
                    func.sum(case((Submission.is_late.is_(True), 1), else_=0)).label("late"),
                    func.sum(case((Submission.is_late.is_(False), 1), else_=0)).label(
                        "on_time"
                    ),
                    func.sum(
                        case((Submission.is_graded.is_(False), 1), else_=0)
                    ).label("pending_review"),
                ).where(Submission.assignment_id.in_(assignment_ids))
            )
            submission_row = submission_q.one()
            total_submissions = int(submission_row.total or 0)
            late_submissions = int(submission_row.late or 0)
            on_time_submissions = int(submission_row.on_time or 0)
            pending_review_submissions = int(submission_row.pending_review or 0)

        attendance_filters = [
            Attendance.teacher_id == teacher_id,
            Student.school_id == school_id,
        ]
        if academic_year_id is not None:
            attendance_filters.append(Attendance.academic_year_id == academic_year_id)
        if standard_id is not None:
            attendance_filters.append(Attendance.standard_id == standard_id)
        if section_normalized is not None:
            attendance_filters.append(
                func.upper(func.trim(Attendance.section)) == section_normalized
            )
        if subject_id is not None:
            attendance_filters.append(Attendance.subject_id == subject_id)

        attendance_q = await self.db.execute(
            select(
                func.count(Attendance.id).label("total"),
                func.sum(case((Attendance.status == AttendanceStatus.PRESENT, 1), else_=0)).label(
                    "present"
                ),
                func.sum(case((Attendance.status == AttendanceStatus.ABSENT, 1), else_=0)).label(
                    "absent"
                ),
                func.sum(case((Attendance.status == AttendanceStatus.LATE, 1), else_=0)).label("late"),
            )
            .join(Student, Student.id == Attendance.student_id)
            .where(and_(*attendance_filters))
        )
        attendance_row = attendance_q.one()
        attendance_total = int(attendance_row.total or 0)
        attendance_present = int(attendance_row.present or 0)
        attendance_absent = int(attendance_row.absent or 0)
        attendance_late = int(attendance_row.late or 0)
        attendance_percentage = (
            (attendance_present / attendance_total) * 100.0 if attendance_total else 0.0
        )

        attendance_by_subject_q = await self.db.execute(
            select(
                Attendance.subject_id,
                Subject.name.label("subject_name"),
                func.count(Attendance.id).label("total"),
                func.sum(case((Attendance.status == AttendanceStatus.PRESENT, 1), else_=0)).label(
                    "present"
                ),
                func.sum(case((Attendance.status == AttendanceStatus.ABSENT, 1), else_=0)).label(
                    "absent"
                ),
                func.sum(case((Attendance.status == AttendanceStatus.LATE, 1), else_=0)).label("late"),
            )
            .join(Subject, Subject.id == Attendance.subject_id)
            .join(Student, Student.id == Attendance.student_id)
            .where(and_(*attendance_filters))
            .group_by(Attendance.subject_id, Subject.name)
            .order_by(Subject.name.asc())
        )
        attendance_by_subject = []
        for row in attendance_by_subject_q.all():
            total = int(row.total or 0)
            present = int(row.present or 0)
            attendance_by_subject.append(
                TeacherAttendanceBySubjectAnalytics(
                    subject_id=row.subject_id,
                    subject_name=row.subject_name,
                    total=total,
                    present=present,
                    absent=int(row.absent or 0),
                    late=int(row.late or 0),
                    attendance_percentage=(present / total) * 100.0 if total else 0.0,
                )
            )

        marks_filters = [
            Result.school_id == school_id,
            Result.entered_by == current_user.id,
        ]
        if academic_year_id is not None:
            marks_filters.append(Exam.academic_year_id == academic_year_id)
        if standard_id is not None:
            marks_filters.append(Exam.standard_id == standard_id)
        if subject_id is not None:
            marks_filters.append(Result.subject_id == subject_id)
        if section_normalized is not None:
            marks_filters.append(func.upper(func.trim(Student.section)) == section_normalized)

        marks_q = await self.db.execute(
            select(
                func.count(Result.id).label("total"),
                func.avg(Result.percentage).label("avg_percentage"),
                func.sum(case((Result.percentage >= 75, 1), else_=0)).label("above"),
                func.sum(
                    case((and_(Result.percentage >= 40, Result.percentage < 75), 1), else_=0)
                ).label("moderate"),
                func.sum(case((Result.percentage < 40, 1), else_=0)).label("below"),
            )
            .join(Exam, Exam.id == Result.exam_id)
            .join(Student, Student.id == Result.student_id)
            .where(and_(*marks_filters))
        )
        marks_row = marks_q.one()
        marks_total = int(marks_row.total or 0)
        marks_avg = float(marks_row.avg_percentage or 0.0)

        marks_by_subject_q = await self.db.execute(
            select(
                Result.subject_id,
                Subject.name.label("subject_name"),
                func.count(Result.id).label("entries"),
                func.avg(Result.percentage).label("avg_percentage"),
            )
            .join(Subject, Subject.id == Result.subject_id)
            .join(Exam, Exam.id == Result.exam_id)
            .join(Student, Student.id == Result.student_id)
            .where(and_(*marks_filters))
            .group_by(Result.subject_id, Subject.name)
            .order_by(Subject.name.asc())
        )
        marks_by_subject = [
            TeacherMarksBySubjectAnalytics(
                subject_id=row.subject_id,
                subject_name=row.subject_name,
                entries=int(row.entries or 0),
                average_percentage=float(row.avg_percentage or 0.0),
            )
            for row in marks_by_subject_q.all()
        ]

        return TeacherAnalyticsResponse(
            teacher_id=teacher_id,
            filters={
                "academic_year_id": str(academic_year_id) if academic_year_id else None,
                "standard_id": str(standard_id) if standard_id else None,
                "section": section_normalized,
                "subject_id": str(subject_id) if subject_id else None,
            },
            assignments=assignments,
            assignment_submission=TeacherAssignmentSubmissionAnalytics(
                total_assignments=total_assignments,
                overdue_assignments=overdue_assignments,
                total_submissions=total_submissions,
                on_time_submissions=on_time_submissions,
                late_submissions=late_submissions,
                pending_review_submissions=pending_review_submissions,
            ),
            attendance=TeacherAttendanceAnalytics(
                total_records=attendance_total,
                present_count=attendance_present,
                absent_count=attendance_absent,
                late_count=attendance_late,
                attendance_percentage=attendance_percentage,
                by_subject=attendance_by_subject,
            ),
            marks=TeacherMarksAnalytics(
                total_entries=marks_total,
                average_percentage=marks_avg,
                above_average_count=int(marks_row.above or 0),
                moderate_count=int(marks_row.moderate or 0),
                below_average_count=int(marks_row.below or 0),
                by_subject=marks_by_subject,
            ),
        )

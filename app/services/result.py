import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import (
    ForbiddenException,
    ConflictException,
    ValidationException,
    NotFoundException,
    AppException,
)
from app.repositories.result import ResultRepository
from app.repositories.notification import NotificationRepository
from app.repositories.teacher_class_subject import TeacherClassSubjectRepository
from app.schemas.result import (
    ExamCreate,
    ExamBulkCreate,
    ExamBulkCreateResponse,
    ExamResponse,
    ResultBulkCreate,
    ResultEntryResponse,
    ResultListResponse,
    ResultDistributionResponse,
    ResultDistributionStudentItem,
    ResultDistributionSubjectItem,
    ResultEntryTableItem,
    ResultEntryTableResponse,
    ReportCardResponse,
    ReportCardUploadResponse,
)
from app.services.academic_year import get_active_year
from app.services.assignment import _get_teacher_id, _assert_teacher_owns_class_subject
from app.services.student import StudentService
from app.integrations.minio_client import minio_client
from app.integrations import pdf_service
from app.utils.enums import (
    RoleEnum,
    NotificationType,
    NotificationPriority,
    DocumentType,
    DocumentStatus,
    ExamType,
)

DOCUMENTS_BUCKET = "documents"


async def _notify_results_published(
    school_id: uuid.UUID,
    standard_id: uuid.UUID,
    exam_id: uuid.UUID,
    exam_name: str,
) -> None:
    """Opens its own DB session — never reuses the request session."""
    from app.db.session import AsyncSessionLocal
    from app.models.student import Student
    from app.models.parent import Parent

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Student.user_id, Student.parent_id).where(
                and_(
                    Student.standard_id == standard_id,
                    Student.school_id == school_id,
                )
            )
        )
        rows = result.all()

        user_ids_to_notify: set[uuid.UUID] = set()
        parent_ids: set[uuid.UUID] = set()

        for student_user_id, parent_id in rows:
            if student_user_id:
                user_ids_to_notify.add(student_user_id)
            if parent_id:
                parent_ids.add(parent_id)

        if parent_ids:
            parent_result = await db.execute(
                select(Parent.user_id).where(Parent.id.in_(list(parent_ids)))
            )
            for (parent_user_id,) in parent_result:
                if parent_user_id:
                    user_ids_to_notify.add(parent_user_id)

        notification_repo = NotificationRepository(db)
        for user_id in user_ids_to_notify:
            await notification_repo.create(
                {
                    "user_id": user_id,
                    "title": "Results Published",
                    "body": f"Results for '{exam_name}' have been published.",
                    "type": NotificationType.RESULT,
                    "priority": NotificationPriority.MEDIUM,
                    "reference_id": exam_id,
                }
            )

        await db.commit()


class ResultService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ResultRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    @staticmethod
    def _infer_exam_type(name: str) -> ExamType:
        label = (name or "").strip().lower()
        if "final" in label:
            return ExamType.FINAL
        if "semester" in label or "half yearly" in label or "half-yearly" in label:
            return ExamType.HALF_YEARLY
        if "mid term" in label or "midterm" in label:
            return ExamType.MID_TERM
        if "annual" in label:
            return ExamType.ANNUAL
        if "quarter" in label:
            return ExamType.QUARTERLY
        if "mock" in label or "pre board" in label or "pre-board" in label:
            return ExamType.MOCK
        if "unit test 2" in label or "ut2" in label:
            return ExamType.UNIT_TEST
        if "unit test 1" in label or "ut1" in label:
            return ExamType.UNIT_TEST
        if "unit test" in label:
            return ExamType.UNIT_TEST
        return ExamType.UNIT_TEST

    @staticmethod
    def _uploaded_report_card_key(
        school_id: uuid.UUID, student_id: uuid.UUID, exam_id: uuid.UUID
    ) -> str:
        return (
            f"{school_id}/{student_id}/report_cards/{exam_id}_uploaded_report_card.pdf"
        )

    @staticmethod
    def _generated_report_card_key(
        school_id: uuid.UUID, student_id: uuid.UUID, exam_id: uuid.UUID
    ) -> str:
        return (
            f"{school_id}/{student_id}/report_cards/{exam_id}_generated_report_card.pdf"
        )

    def _resolve_report_card_url(
        self,
        *,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
        exam_id: uuid.UUID,
    ) -> Optional[str]:
        uploaded_file_key = self._uploaded_report_card_key(school_id, student_id, exam_id)
        if minio_client.file_exists(DOCUMENTS_BUCKET, uploaded_file_key):
            return minio_client.generate_presigned_url(
                DOCUMENTS_BUCKET, uploaded_file_key
            )

        generated_file_key = self._generated_report_card_key(
            school_id, student_id, exam_id
        )
        if minio_client.file_exists(DOCUMENTS_BUCKET, generated_file_key):
            return minio_client.generate_presigned_url(
                DOCUMENTS_BUCKET, generated_file_key
            )

        return None

    async def _assert_exam_student_access(
        self,
        *,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
        exam_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> bool:
        """
        Returns whether only published results should be visible.
        """
        from app.models.student import Student

        published_only = False

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_student_id = result.scalar_one_or_none()
            if not own_student_id or own_student_id != student_id:
                raise ForbiddenException("You can only view your own results")
            published_only = False

        elif current_user.role == RoleEnum.PARENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.id == student_id,
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == school_id,
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise ForbiddenException("Not your child")
            published_only = False

        elif current_user.role == RoleEnum.TEACHER:
            exam = await self.repo.get_exam_by_id(exam_id, school_id)
            if not exam:
                raise NotFoundException("Exam")

            student_row = await self.db.execute(
                select(Student.standard_id, Student.section).where(
                    and_(
                        Student.id == student_id,
                        Student.school_id == school_id,
                    )
                )
            )
            row = student_row.one_or_none()
            student_standard_id = row[0] if row else None
            student_section = row[1].strip() if row and row[1] else None

            if not student_standard_id or student_standard_id != exam.standard_id:
                raise ForbiddenException("Student not in this exam's class")

            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
            assignment_repo = TeacherClassSubjectRepository(self.db)
            teacher_assignments, _ = await assignment_repo.list_by_teacher(
                teacher_id=teacher_id,
                academic_year_id=exam.academic_year_id,
            )
            teaches_class_or_section = any(
                assignment.standard_id == exam.standard_id
                and (
                    student_section is None
                    or (assignment.section or "").strip() == student_section
                )
                for assignment in teacher_assignments
            )
            if not teaches_class_or_section:
                historical_entries = await self.repo.list_results(
                    school_id=school_id,
                    student_id=student_id,
                    exam_id=exam_id,
                    entered_by=current_user.id,
                )
                if not historical_entries:
                    raise ForbiddenException(
                        "You can only view results for sections you taught or marks entered by you"
                    )

        return published_only

    async def create_exam(
        self,
        body: ExamCreate,
        current_user: CurrentUser,
    ) -> ExamResponse:
        school_id = self._ensure_school(current_user)
        if current_user.role != RoleEnum.STAFF_ADMIN:
            raise ForbiddenException("Only staff admin can define exams")

        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        if body.end_date < body.start_date:
            raise ValidationException("end_date must be on or after start_date")

        existing = await self.repo.get_exam_duplicate(
            school_id=school_id,
            standard_id=body.standard_id,
            academic_year_id=academic_year_id,
            name=body.name,
        )
        if existing:
            raise ConflictException("Exam already exists for this class and year")

        exam = await self.repo.create_exam(
            {
                "name": body.name,
                "exam_type": self._infer_exam_type(body.name),
                "standard_id": body.standard_id,
                "academic_year_id": academic_year_id,
                "start_date": body.start_date,
                "end_date": body.end_date,
                "created_by": current_user.id,
                "school_id": school_id,
            }
        )
        await self.db.refresh(exam)
        return ExamResponse.model_validate(exam)

    async def create_exams_bulk(
        self,
        body: ExamBulkCreate,
        current_user: CurrentUser,
    ) -> ExamBulkCreateResponse:
        school_id = self._ensure_school(current_user)
        if current_user.role != RoleEnum.STAFF_ADMIN:
            raise ForbiddenException("Only staff admin can define exams")

        if body.end_date < body.start_date:
            raise ValidationException("end_date must be on or after start_date")

        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        from app.models.masters import Standard

        standard_ids: list[uuid.UUID] = []
        if body.apply_to_all_standards:
            result = await self.db.execute(
                select(Standard.id).where(
                    and_(
                        Standard.school_id == school_id,
                        Standard.academic_year_id == academic_year_id,
                    )
                )
            )
            standard_ids = [row[0] for row in result.all()]
            if not standard_ids:
                raise ValidationException("No classes found for selected academic year")
        else:
            standard_ids = list(dict.fromkeys(body.standard_ids or []))
            if not standard_ids:
                raise ValidationException(
                    "standard_ids is required when apply_to_all_standards is false"
                )
            existing_standard_rows = await self.db.execute(
                select(Standard.id).where(
                    and_(
                        Standard.id.in_(standard_ids),
                        Standard.school_id == school_id,
                    )
                )
            )
            existing_standard_ids = {row[0] for row in existing_standard_rows.all()}
            missing = [sid for sid in standard_ids if sid not in existing_standard_ids]
            if missing:
                raise ValidationException("One or more class IDs are invalid")

        created: list[ExamResponse] = []
        skipped_standard_ids: list[uuid.UUID] = []

        for standard_id in standard_ids:
            duplicate = await self.repo.get_exam_duplicate(
                school_id=school_id,
                standard_id=standard_id,
                academic_year_id=academic_year_id,
                name=body.name,
            )
            if duplicate:
                skipped_standard_ids.append(standard_id)
                continue

            exam = await self.repo.create_exam(
                {
                    "name": body.name,
                    "exam_type": self._infer_exam_type(body.name),
                    "standard_id": standard_id,
                    "academic_year_id": academic_year_id,
                    "start_date": body.start_date,
                    "end_date": body.end_date,
                    "created_by": current_user.id,
                    "school_id": school_id,
                }
            )
            created.append(ExamResponse.model_validate(exam))

        return ExamBulkCreateResponse(
            created=created,
            created_count=len(created),
            skipped_standard_ids=skipped_standard_ids,
            skipped_count=len(skipped_standard_ids),
        )

    async def list_exams(
        self,
        current_user: CurrentUser,
        student_id: Optional[uuid.UUID],
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
    ) -> list[ExamResponse]:
        school_id = self._ensure_school(current_user)

        from app.models.student import Student

        resolved_student_id = student_id
        published_only = False

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_student_id = result.scalar_one_or_none()
            if not own_student_id:
                raise NotFoundException("Student")
            if resolved_student_id and resolved_student_id != own_student_id:
                raise ForbiddenException("You can only view your own exams")
            resolved_student_id = own_student_id
            published_only = False

        elif current_user.role == RoleEnum.PARENT:
            if resolved_student_id is None:
                raise ValidationException("student_id is required for parent users")
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.id == resolved_student_id,
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == school_id,
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise ForbiddenException("Not your child")
            published_only = False

        elif resolved_student_id is not None:
            exists = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.id == resolved_student_id,
                        Student.school_id == school_id,
                    )
                )
            )
            if not exists.scalar_one_or_none():
                raise NotFoundException("Student")

        teacher_standard_ids: Optional[list[uuid.UUID]] = None
        teacher_id: Optional[uuid.UUID] = None
        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
            assignment_repo = TeacherClassSubjectRepository(self.db)
            assignments, _ = await assignment_repo.list_by_teacher(
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
            )
            teacher_standard_ids = list(
                {assignment.standard_id for assignment in assignments}
            )
            if standard_id is not None and standard_id not in teacher_standard_ids:
                # Allow historical review only when this teacher has entered marks
                # for exams in that class.
                historical = await self.repo.list_exams_entered_by(
                    school_id=school_id,
                    entered_by=current_user.id,
                    academic_year_id=academic_year_id,
                    standard_id=standard_id,
                    student_id=resolved_student_id,
                    published_only=published_only,
                )
                if not historical:
                    raise ForbiddenException(
                        "You can only view exams for assigned classes or classes where you entered marks"
                    )
                exams = historical
                return [ExamResponse.model_validate(exam) for exam in exams]

        exams: list = []
        if current_user.role == RoleEnum.TEACHER:
            assigned_exams = await self.repo.list_exams(
                school_id=school_id,
                academic_year_id=academic_year_id,
                standard_id=standard_id,
                standard_ids=teacher_standard_ids if standard_id is None else None,
                student_id=resolved_student_id,
                published_only=published_only,
            )
            historical_exams = await self.repo.list_exams_entered_by(
                school_id=school_id,
                entered_by=current_user.id,
                academic_year_id=academic_year_id,
                standard_id=standard_id,
                student_id=resolved_student_id,
                published_only=published_only,
            )
            by_id = {exam.id: exam for exam in assigned_exams}
            for exam in historical_exams:
                by_id.setdefault(exam.id, exam)
            exams = sorted(
                by_id.values(),
                key=lambda exam: (exam.start_date, exam.created_at),
                reverse=True,
            )
        else:
            exams = await self.repo.list_exams(
                school_id=school_id,
                academic_year_id=academic_year_id,
                standard_id=standard_id,
                standard_ids=teacher_standard_ids if standard_id is None else None,
                student_id=resolved_student_id,
                published_only=published_only,
            )
        return [ExamResponse.model_validate(exam) for exam in exams]

    async def bulk_enter_results(
        self,
        body: ResultBulkCreate,
        current_user: CurrentUser,
    ) -> ResultListResponse:
        school_id = self._ensure_school(current_user)
        if current_user.role not in (
            RoleEnum.TEACHER,
            RoleEnum.PRINCIPAL,
            RoleEnum.STAFF_ADMIN,
        ):
            raise ForbiddenException("Only teachers/principal/staff admin can enter results")

        exam = await self.repo.get_exam_by_id(body.exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

        teacher_id: Optional[uuid.UUID] = None
        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)

        results: list[ResultEntryResponse] = []
        from app.models.student import Student
        from app.models.masters import GradeMaster

        assignment_repo = TeacherClassSubjectRepository(self.db)
        for entry in body.entries:
            student_result = await self.db.execute(
                select(Student.standard_id, Student.section).where(
                    and_(
                        Student.id == entry.student_id,
                        Student.school_id == school_id,
                    )
                )
            )
            student_row = student_result.one_or_none()
            student_standard_id = student_row[0] if student_row else None
            student_section = student_row[1].strip() if student_row and student_row[1] else None
            if not student_standard_id or student_standard_id != exam.standard_id:
                raise ForbiddenException("Student not in this exam's class")

            if current_user.role == RoleEnum.TEACHER:
                if student_section:
                    section_assignment = await assignment_repo.find_assignment_with_section(
                        teacher_id=teacher_id,
                        standard_id=exam.standard_id,
                        section=student_section,
                        subject_id=entry.subject_id,
                        academic_year_id=exam.academic_year_id,
                    )
                    if not section_assignment:
                        raise ForbiddenException(
                            "You are not assigned to this subject for the student's section"
                        )
                else:
                    await _assert_teacher_owns_class_subject(
                        self.db,
                        teacher_id=teacher_id,
                        standard_id=exam.standard_id,
                        subject_id=entry.subject_id,
                        academic_year_id=exam.academic_year_id,
                    )

            existing = await self.repo.get_result_existing(
                body.exam_id, entry.student_id, entry.subject_id
            )
            percentage = round((entry.marks_obtained / entry.max_marks) * 100, 2)

            grade_row = await self.db.execute(
                select(GradeMaster).where(
                    and_(
                        GradeMaster.school_id == school_id,
                        GradeMaster.min_percent <= percentage,
                        GradeMaster.max_percent >= percentage,
                    )
                )
            )
            grade = grade_row.scalar_one_or_none()
            if not grade:
                raise ValidationException("No grade mapping found for percentage")

            payload = {
                "marks_obtained": entry.marks_obtained,
                "max_marks": entry.max_marks,
                "percentage": percentage,
                "grade_id": grade.id,
                "entered_by": current_user.id,
            }
            if existing:
                result = await self.repo.update_result(existing, payload)
            else:
                result = await self.repo.create_result(
                    {
                        "exam_id": body.exam_id,
                        "student_id": entry.student_id,
                        "subject_id": entry.subject_id,
                        "is_published": False,
                        "school_id": school_id,
                        **payload,
                    }
                )
            results.append(ResultEntryResponse.model_validate(result))

        return ResultListResponse(items=results, total=len(results))

    async def list_result_entries(
        self,
        *,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID],
        standard_id: Optional[uuid.UUID],
        section: Optional[str],
        exam_id: Optional[uuid.UUID],
    ) -> ResultEntryTableResponse:
        school_id = self._ensure_school(current_user)
        if current_user.role not in (
            RoleEnum.PRINCIPAL,
            RoleEnum.TRUSTEE,
            RoleEnum.STAFF_ADMIN,
        ):
            raise ForbiddenException("Only management roles can view all result entries")

        rows = await self.repo.list_results_filtered(
            school_id=school_id,
            academic_year_id=academic_year_id,
            standard_id=standard_id,
            section=section,
            exam_id=exam_id,
        )
        items: list[ResultEntryTableItem] = []
        for row in rows:
            if row.exam is None:
                continue
            student_name = "Student"
            if row.student:
                student_name = row.student.student_name or row.student.admission_number
            subject_name = row.subject.name if row.subject else "Subject"
            entered_by_name = row.enterer.full_name if row.enterer else None
            exam_name = row.exam.name
            items.append(
                ResultEntryTableItem(
                    id=row.id,
                    exam_id=row.exam_id,
                    exam_name=exam_name,
                    academic_year_id=row.exam.academic_year_id,
                    standard_id=row.exam.standard_id,
                    student_id=row.student_id,
                    student_name=student_name,
                    admission_number=row.student.admission_number if row.student else "",
                    section=row.student.section if row.student else None,
                    subject_id=row.subject_id,
                    subject_name=subject_name,
                    marks_obtained=float(row.marks_obtained),
                    max_marks=float(row.max_marks),
                    percentage=float(row.percentage),
                    is_published=row.is_published,
                    entered_by=row.entered_by,
                    entered_by_name=entered_by_name,
                    entered_at=row.entered_at,
                    updated_at=row.updated_at,
                )
            )

        return ResultEntryTableResponse(items=items, total=len(items))

    async def publish_exam(
        self,
        exam_id: uuid.UUID,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> int:
        school_id = self._ensure_school(current_user)
        if current_user.role not in (RoleEnum.PRINCIPAL, RoleEnum.STAFF_ADMIN):
            raise ForbiddenException("Only principal or staff admin can publish results")

        exam = await self.repo.get_exam_by_id(exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

        updated_count = await self.repo.publish_exam_results(exam_id, school_id)

        background_tasks.add_task(
            _notify_results_published,
            school_id,
            exam.standard_id,
            exam.id,
            exam.name,
        )
        return updated_count

    async def delete_exam(
        self,
        exam_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> None:
        school_id = self._ensure_school(current_user)
        if current_user.role not in (RoleEnum.PRINCIPAL, RoleEnum.STAFF_ADMIN):
            raise ForbiddenException("Only principal or staff admin can delete exams")

        exam = await self.repo.get_exam_by_id(exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

        await self.repo.delete_exam(exam)

    async def list_results(
        self,
        student_id: uuid.UUID,
        exam_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> ResultListResponse:
        school_id = self._ensure_school(current_user)
        published_only = await self._assert_exam_student_access(
            school_id=school_id,
            student_id=student_id,
            exam_id=exam_id,
            current_user=current_user,
        )

        results = await self.repo.list_results(
            school_id=school_id,
            student_id=student_id,
            exam_id=exam_id,
            published_only=published_only,
            entered_by=current_user.id if current_user.role == RoleEnum.TEACHER else None,
        )
        report_card_url = self._resolve_report_card_url(
            school_id=school_id,
            student_id=student_id,
            exam_id=exam_id,
        )
        return ResultListResponse(
            items=[ResultEntryResponse.model_validate(r) for r in results],
            total=len(results),
            report_card_url=report_card_url,
            has_report_card=report_card_url is not None,
        )

    async def generate_report_card(
        self,
        student_id: uuid.UUID,
        exam_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> ReportCardResponse:
        school_id = self._ensure_school(current_user)
        from app.models.document import Document
        published_only = await self._assert_exam_student_access(
            school_id=school_id,
            student_id=student_id,
            exam_id=exam_id,
            current_user=current_user,
        )

        uploaded_file_key = (
            self._uploaded_report_card_key(school_id, student_id, exam_id)
        )
        if minio_client.file_exists(DOCUMENTS_BUCKET, uploaded_file_key):
            return ReportCardResponse(
                url=minio_client.generate_presigned_url(
                    DOCUMENTS_BUCKET, uploaded_file_key
                )
            )

        generated_file_key = self._generated_report_card_key(
            school_id, student_id, exam_id
        )
        if minio_client.file_exists(DOCUMENTS_BUCKET, generated_file_key):
            return ReportCardResponse(
                url=minio_client.generate_presigned_url(
                    DOCUMENTS_BUCKET, generated_file_key
                )
            )

        results = await self.repo.list_results(
            school_id=school_id,
            student_id=student_id,
            exam_id=exam_id,
            published_only=published_only,
        )
        if not results:
            raise NotFoundException("Results")

        exam = await self.repo.get_exam_by_id(exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

        rows = "".join(
            f"<tr><td>{r.subject_id}</td><td>{r.marks_obtained}</td><td>{r.max_marks}</td>"
            f"<td>{r.percentage}</td></tr>"
            for r in results
        )
        html = f"""
        <html><body>
        <h2>Report Card</h2>
        <p>Student ID: {student_id}</p>
        <p>Exam: {exam.name}</p>
        <table border="1" cellpadding="6" cellspacing="0">
        <tr><th>Subject</th><th>Marks</th><th>Max</th><th>Percentage</th></tr>
        {rows}
        </table>
        </body></html>
        """
        try:
            pdf_bytes = pdf_service.generate_pdf(html)
        except RuntimeError as exc:
            # Avoid raw 500 traces when host machine lacks WeasyPrint native libs.
            # Teachers/principal can still upload a report-card PDF via
            # /results/report-card/upload.
            raise AppException(
                status_code=503,
                detail=(
                    "Auto PDF generation is temporarily unavailable on this server. "
                    "Please upload report card PDF manually, or install WeasyPrint "
                    "native dependencies (glib/pango/cairo)."
                ),
                error_code="PDF_GENERATION_UNAVAILABLE",
            ) from exc
        file_key = generated_file_key
        minio_client.upload_file(
            bucket=DOCUMENTS_BUCKET,
            key=file_key,
            file_bytes=pdf_bytes,
            content_type="application/pdf",
        )

        doc = Document(
            student_id=student_id,
            document_type=DocumentType.REPORT_CARD,
            file_key=file_key,
            status=DocumentStatus.APPROVED,
            generated_at=datetime.now(timezone.utc),
            academic_year_id=exam.academic_year_id,
            school_id=school_id,
        )
        self.db.add(doc)

        url = minio_client.generate_presigned_url(DOCUMENTS_BUCKET, file_key)
        return ReportCardResponse(url=url)

    async def upload_report_card(
        self,
        *,
        student_id: uuid.UUID,
        exam_id: uuid.UUID,
        file: UploadFile,
        current_user: CurrentUser,
    ) -> ReportCardUploadResponse:
        school_id = self._ensure_school(current_user)
        if current_user.role not in (
            RoleEnum.TEACHER,
            RoleEnum.PRINCIPAL,
            RoleEnum.STAFF_ADMIN,
        ):
            raise ForbiddenException("Only teacher/principal can upload report cards")

        await self._assert_exam_student_access(
            school_id=school_id,
            student_id=student_id,
            exam_id=exam_id,
            current_user=current_user,
        )

        exam = await self.repo.get_exam_by_id(exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

        content_type = (file.content_type or "").lower()
        file_name = (file.filename or "").lower()
        if "pdf" not in content_type and not file_name.endswith(".pdf"):
            raise ValidationException("Only PDF report cards are allowed")

        file_bytes = await file.read()
        if not file_bytes:
            raise ValidationException("Uploaded report card is empty")

        file_key = self._uploaded_report_card_key(school_id, student_id, exam_id)
        minio_client.upload_file(
            bucket=DOCUMENTS_BUCKET,
            key=file_key,
            file_bytes=file_bytes,
            content_type="application/pdf",
        )

        from app.models.document import Document

        doc = Document(
            student_id=student_id,
            document_type=DocumentType.REPORT_CARD,
            file_key=file_key,
            status=DocumentStatus.APPROVED,
            generated_at=datetime.now(timezone.utc),
            academic_year_id=exam.academic_year_id,
            school_id=school_id,
        )
        self.db.add(doc)

        return ReportCardUploadResponse(
            url=minio_client.generate_presigned_url(DOCUMENTS_BUCKET, file_key),
            uploaded=True,
        )

    async def exam_distribution(
        self,
        exam_id: uuid.UUID,
        current_user: CurrentUser,
        section: Optional[str] = None,
        student_id: Optional[uuid.UUID] = None,
    ) -> ResultDistributionResponse:
        school_id = self._ensure_school(current_user)

        exam = await self.repo.get_exam_by_id(exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

        rows = await self.repo.list_results_by_exam(
            school_id=school_id,
            exam_id=exam_id,
            entered_by=current_user.id if current_user.role == RoleEnum.TEACHER else None,
        )
        teacher_has_class_scope = False
        teacher_assigned_sections: set[str] = set()

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
            assignment_repo = TeacherClassSubjectRepository(self.db)
            assignments, _ = await assignment_repo.list_by_teacher(
                teacher_id=teacher_id,
                academic_year_id=exam.academic_year_id,
            )
            class_assignments = [
                assignment
                for assignment in assignments
                if assignment.standard_id == exam.standard_id
            ]
            if class_assignments:
                teacher_assigned_sections = {
                    (assignment.section or "").strip()
                    for assignment in class_assignments
                    if (assignment.section or "").strip()
                }
                teacher_has_class_scope = any(
                    not (assignment.section or "").strip()
                    for assignment in class_assignments
                )
            else:
                # No current assignment for this class: allow teacher to review
                # only historically entered marks (rows already scoped by entered_by).
                teacher_has_class_scope = True
        elif current_user.role not in (
            RoleEnum.PRINCIPAL,
            RoleEnum.TRUSTEE,
            RoleEnum.STAFF_ADMIN,
        ):
            raise ForbiddenException("Only management or assigned teachers can view exam distribution")

        normalized_section = section.strip() if section and section.strip() else None
        if normalized_section is not None:
            if current_user.role == RoleEnum.TEACHER:
                if (
                    not teacher_has_class_scope
                    and normalized_section not in teacher_assigned_sections
                ):
                    raise ForbiddenException("You can only view your assigned sections")
            rows = [
                row for row in rows
                if row.student and (row.student.section or "").strip() == normalized_section
            ]

        if student_id is not None:
            rows = [row for row in rows if row.student_id == student_id]

        grouped: dict[uuid.UUID, list] = {}
        for row in rows:
            grouped.setdefault(row.student_id, []).append(row)

        items: list[ResultDistributionStudentItem] = []
        for _, student_rows in grouped.items():
            student_rows.sort(key=lambda r: (r.subject.name if r.subject else ""))
            student = student_rows[0].student

            subject_items: list[ResultDistributionSubjectItem] = []
            total_obtained = 0.0
            total_max = 0.0
            for row in student_rows:
                marks_obtained = float(row.marks_obtained)
                max_marks = float(row.max_marks)
                total_obtained += marks_obtained
                total_max += max_marks
                subject_items.append(
                    ResultDistributionSubjectItem(
                        subject_id=row.subject_id,
                        subject_name=row.subject.name if row.subject else "Subject",
                        marks_obtained=marks_obtained,
                        max_marks=max_marks,
                        percentage=float(row.percentage),
                        grade_letter=row.grade.grade_letter if row.grade else None,
                        is_published=row.is_published,
                        entered_by_name=row.enterer.full_name if row.enterer else None,
                    )
                )

            overall_percentage = round((total_obtained / total_max) * 100, 2) if total_max > 0 else 0.0

            student_name = student.student_name if student else None
            if not student_name and student:
                student_name = student.admission_number
            if not student_name:
                student_name = "Student"

            report_card_url = self._resolve_report_card_url(
                school_id=school_id,
                student_id=student_rows[0].student_id,
                exam_id=exam_id,
            )

            items.append(
                ResultDistributionStudentItem(
                    student_id=student_rows[0].student_id,
                    student_name=student_name,
                    admission_number=student.admission_number if student else "",
                    section=student.section if student else None,
                    roll_number=student.roll_number if student else None,
                    total_obtained=round(total_obtained, 2),
                    total_max=round(total_max, 2),
                    overall_percentage=overall_percentage,
                    report_card_url=report_card_url,
                    has_report_card=report_card_url is not None,
                    subjects=subject_items,
                )
            )

        items.sort(key=lambda i: i.student_name.lower())
        return ResultDistributionResponse(
            exam=ExamResponse.model_validate(exam),
            total_students=len(items),
            items=items,
        )

    async def list_result_sections(
        self,
        *,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
    ) -> list[str]:
        school_id = self._ensure_school(current_user)

        sections = await StudentService(self.db).list_sections(
            school_id=school_id,
            current_user=current_user,
            standard_id=standard_id,
            academic_year_id=academic_year_id,
        )

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
            assignment_repo = TeacherClassSubjectRepository(self.db)
            assignments, _ = await assignment_repo.list_by_teacher(
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
            )
            class_assignments = [
                assignment
                for assignment in assignments
                if assignment.standard_id == standard_id
            ]
            # If teacher assignments are section-scoped, restrict output accordingly.
            assigned_sections = {
                (assignment.section or "").strip()
                for assignment in class_assignments
                if (assignment.section or "").strip()
            }
            historical_sections = await self.repo.list_sections_for_standard(
                school_id=school_id,
                standard_id=standard_id,
                academic_year_id=academic_year_id,
                entered_by=current_user.id,
            )

            if not class_assignments and not historical_sections:
                raise ForbiddenException(
                    "You can only view sections for assigned classes or classes where you entered marks"
                )

            if assigned_sections:
                sections = [s for s in sections if s in assigned_sections]

            sections = sorted(set(sections).union(historical_sections), key=str.lower)

        return sections

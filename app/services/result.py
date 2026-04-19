import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ConflictException, ValidationException, NotFoundException
from app.repositories.result import ResultRepository
from app.repositories.notification import NotificationRepository
from app.repositories.teacher_class_subject import TeacherClassSubjectRepository
from app.schemas.result import (
    ExamCreate,
    ExamResponse,
    ResultBulkCreate,
    ResultEntryResponse,
    ResultListResponse,
    ResultDistributionResponse,
    ResultDistributionStudentItem,
    ResultDistributionSubjectItem,
    ReportCardResponse,
    ReportCardUploadResponse,
)
from app.services.academic_year import get_active_year
from app.services.assignment import _get_teacher_id, _assert_teacher_owns_class_subject
from app.integrations.minio_client import minio_client
from app.integrations import pdf_service
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority, DocumentType, DocumentStatus

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
            published_only = True

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
            published_only = True

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
                raise ForbiddenException(
                    "You can only view results for sections you taught"
                )

        return published_only

    async def create_exam(
        self,
        body: ExamCreate,
        current_user: CurrentUser,
    ) -> ExamResponse:
        school_id = self._ensure_school(current_user)
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

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
            assignment_repo = TeacherClassSubjectRepository(self.db)
            assignments, _ = await assignment_repo.list_by_teacher(
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
            )
            can_create_for_standard = any(
                assignment.standard_id == body.standard_id for assignment in assignments
            )
            if not can_create_for_standard:
                raise ForbiddenException(
                    "You can create exams only for classes assigned to you"
                )

        exam = await self.repo.create_exam(
            {
                "name": body.name,
                "exam_type": body.exam_type,
                "standard_id": body.standard_id,
                "academic_year_id": academic_year_id,
                "start_date": body.start_date,
                "end_date": body.end_date,
                "created_by": current_user.id,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(exam)
        return ExamResponse.model_validate(exam)

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
                raise ForbiddenException("You can only view exams for assigned classes")

        exams = await self.repo.list_exams(
            school_id=school_id,
            academic_year_id=academic_year_id,
            standard_id=standard_id,
            standard_ids=teacher_standard_ids if standard_id is None else None,
            student_id=resolved_student_id,
        )
        return [ExamResponse.model_validate(exam) for exam in exams]

    async def bulk_enter_results(
        self,
        body: ResultBulkCreate,
        current_user: CurrentUser,
    ) -> ResultListResponse:
        school_id = self._ensure_school(current_user)

        exam = await self.repo.get_exam_by_id(body.exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

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
            if existing:
                raise ConflictException(
                    "Result already exists for this student and subject"
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

            result = await self.repo.create_result(
                {
                    "exam_id": body.exam_id,
                    "student_id": entry.student_id,
                    "subject_id": entry.subject_id,
                    "marks_obtained": entry.marks_obtained,
                    "max_marks": entry.max_marks,
                    "percentage": percentage,
                    "grade_id": grade.id,
                    "is_published": False,
                    "entered_by": current_user.id,
                    "school_id": school_id,
                }
            )
            results.append(ResultEntryResponse.model_validate(result))

        await self.db.commit()
        return ResultListResponse(items=results, total=len(results))

    async def publish_exam(
        self,
        exam_id: uuid.UUID,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> int:
        school_id = self._ensure_school(current_user)

        exam = await self.repo.get_exam_by_id(exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

        updated_count = await self.repo.publish_exam_results(exam_id, school_id)
        await self.db.commit()

        background_tasks.add_task(
            _notify_results_published,
            school_id,
            exam.standard_id,
            exam.id,
            exam.name,
        )
        return updated_count

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
        )
        if current_user.role == RoleEnum.TEACHER:
            results = [r for r in results if r.entered_by == current_user.id]
            if not results:
                raise ForbiddenException(
                    "You can only view results that were entered by you"
                )
        return ResultListResponse(
            items=[ResultEntryResponse.model_validate(r) for r in results],
            total=len(results),
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
            f"{school_id}/{student_id}/report_cards/{exam_id}_uploaded_report_card.pdf"
        )
        if minio_client.file_exists(DOCUMENTS_BUCKET, uploaded_file_key):
            return ReportCardResponse(
                url=minio_client.generate_presigned_url(
                    DOCUMENTS_BUCKET, uploaded_file_key
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
        pdf_bytes = pdf_service.generate_pdf(html)
        file_key = f"{school_id}/{student_id}/{uuid.uuid4()}_report_card.pdf"
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
            status=DocumentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            academic_year_id=exam.academic_year_id,
            school_id=school_id,
        )
        self.db.add(doc)
        await self.db.commit()

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
            RoleEnum.SUPERADMIN,
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

        file_key = (
            f"{school_id}/{student_id}/report_cards/{exam_id}_uploaded_report_card.pdf"
        )
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
            status=DocumentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            academic_year_id=exam.academic_year_id,
            school_id=school_id,
        )
        self.db.add(doc)
        await self.db.commit()

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

        if current_user.role not in (
            RoleEnum.PRINCIPAL,
            RoleEnum.TRUSTEE,
            RoleEnum.SUPERADMIN,
        ):
            raise ForbiddenException("Only management can view exam distribution")

        exam = await self.repo.get_exam_by_id(exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

        rows = await self.repo.list_results_by_exam(
            school_id=school_id,
            exam_id=exam_id,
        )

        normalized_section = section.strip() if section and section.strip() else None
        if normalized_section is not None:
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
                    )
                )

            overall_percentage = round((total_obtained / total_max) * 100, 2) if total_max > 0 else 0.0

            student_name = student.student_name if student else None
            if not student_name and student:
                student_name = student.admission_number
            if not student_name:
                student_name = "Student"

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

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
            assignment_repo = TeacherClassSubjectRepository(self.db)
            assignments, _ = await assignment_repo.list_by_teacher(
                teacher_id=teacher_id,
                academic_year_id=academic_year_id,
            )
            if not any(assignment.standard_id == standard_id for assignment in assignments):
                raise ForbiddenException("You can only view sections for assigned classes")

        return await self.repo.list_sections_for_standard(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=academic_year_id,
        )

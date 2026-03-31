import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ConflictException, ValidationException, NotFoundException
from app.repositories.result import ResultRepository
from app.repositories.notification import NotificationRepository
from app.schemas.result import (
    ExamCreate,
    ExamResponse,
    ResultBulkCreate,
    ResultEntryResponse,
    ResultListResponse,
    ReportCardResponse,
)
from app.services.academic_year import get_active_year
from app.services.assignment import _get_teacher_id, _assert_teacher_owns_class_subject
from app.integrations.minio_client import minio_client
from app.integrations import pdf_service
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority, DocumentType, DocumentStatus

DOCUMENTS_BUCKET = "documents"


async def _notify_results_published(
    db: AsyncSession,
    school_id: uuid.UUID,
    standard_id: uuid.UUID,
    exam_id: uuid.UUID,
    exam_name: str,
) -> None:
    from app.models.student import Student
    from app.models.parent import Parent

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

        for entry in body.entries:
            # Scope: teacher must own class+subject for this exam
            await _assert_teacher_owns_class_subject(
                self.db,
                teacher_id=teacher_id,
                standard_id=exam.standard_id,
                subject_id=entry.subject_id,
                academic_year_id=exam.academic_year_id,
            )

            student_result = await self.db.execute(
                select(Student.standard_id).where(
                    and_(
                        Student.id == entry.student_id,
                        Student.school_id == school_id,
                    )
                )
            )
            student_standard_id = student_result.scalar_one_or_none()
            if not student_standard_id or student_standard_id != exam.standard_id:
                raise ForbiddenException("Student not in this exam's class")

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
            self.db,
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

        results = await self.repo.list_results(
            school_id=school_id,
            student_id=student_id,
            exam_id=exam_id,
            published_only=published_only,
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

        from app.models.student import Student
        from app.models.document import Document

        if current_user.role == RoleEnum.PARENT:
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
                raise ForbiddenException("You can only view your own report card")

        results = await self.repo.list_results(
            school_id=school_id,
            student_id=student_id,
            exam_id=exam_id,
            published_only=current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT),
        )
        if not results:
            raise NotFoundException("Results")

        exam = await self.repo.get_exam_by_id(exam_id, school_id)
        if not exam:
            raise NotFoundException("Exam")

        # Render a very simple HTML report
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

import uuid
import math
from datetime import date, datetime, timezone
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
)
from app.repositories.homework import HomeworkRepository
from app.repositories.homework_submission import HomeworkSubmissionRepository
from app.repositories.notification import NotificationRepository
from app.repositories.student import StudentRepository
from app.schemas.homework import (
    HomeworkCreate,
    HomeworkResponse,
    HomeworkListResponse,
    HomeworkSubmissionCreate,
    HomeworkSubmissionReview,
    HomeworkSubmissionResponse,
    HomeworkSubmissionListResponse,
)
from app.services.academic_year import get_active_year
from app.services.assignment import _get_teacher_id, _assert_teacher_owns_class_subject
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority
from app.integrations.minio_client import minio_client
from app.models.homework_submission import HomeworkSubmission

HOMEWORK_BUCKET = "homework"
HOMEWORK_RESPONSE_BUCKET = "homework-submissions"


async def _notify_homework_created(
    school_id: uuid.UUID,
    standard_id: uuid.UUID,
    homework_id: uuid.UUID,
    record_date: date,
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
                    "title": "New Homework Posted",
                    "body": f"New homework has been posted for {record_date.isoformat()}",
                    "type": NotificationType.HOMEWORK,
                    "priority": NotificationPriority.LOW,
                    "reference_id": homework_id,
                }
            )

        await db.commit()


class HomeworkService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = HomeworkRepository(db)
        self.submission_repo = HomeworkSubmissionRepository(db)
        self.student_repo = StudentRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    def _build_homework_response(
        self,
        homework,
        *,
        is_submitted: Optional[bool] = None,
    ) -> HomeworkResponse:
        data = HomeworkResponse.model_validate(homework)
        if getattr(homework, "file_key", None):
            data.file_url = minio_client.generate_presigned_url(
                HOMEWORK_BUCKET, homework.file_key
            )
        data.is_submitted = is_submitted
        return data

    async def create_homework(
        self,
        body: HomeworkCreate,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
        file: Optional[UploadFile] = None,
    ) -> HomeworkResponse:
        school_id = self._ensure_school(current_user)

        record_date = body.date or datetime.now(timezone.utc).date()
        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
        await _assert_teacher_owns_class_subject(
            self.db,
            teacher_id=teacher_id,
            standard_id=body.standard_id,
            subject_id=body.subject_id,
            academic_year_id=academic_year_id,
        )

        existing = await self.repo.get_duplicate(
            school_id=school_id,
            standard_id=body.standard_id,
            subject_id=body.subject_id,
            record_date=record_date,
            academic_year_id=academic_year_id,
        )
        if existing:
            raise ConflictException("Homework already exists for this class and date")

        description = body.description.strip() if body.description else None
        file_key: Optional[str] = None
        if file and file.filename:
            content = await file.read()
            if not content:
                raise ValidationException("Uploaded homework file is empty")
            file_key = (
                f"{school_id}/{body.standard_id}/{body.subject_id}/"
                f"{uuid.uuid4()}_{file.filename}"
            )
            minio_client.upload_file(
                bucket=HOMEWORK_BUCKET,
                key=file_key,
                file_bytes=content,
                content_type=file.content_type or "application/octet-stream",
            )
        if description is None and file_key is None:
            raise ValidationException("Provide homework text or attach a file")
        if description is None:
            description = "Homework file attached. Please open attachment."

        homework = await self.repo.create(
            {
                "description": description,
                "file_key": file_key,
                "date": record_date,
                "teacher_id": teacher_id,
                "standard_id": body.standard_id,
                "subject_id": body.subject_id,
                "academic_year_id": academic_year_id,
                "school_id": school_id,
            }
        )
        await self.db.refresh(homework)

        background_tasks.add_task(
            _notify_homework_created,
            school_id,
            body.standard_id,
            homework.id,
            record_date,
        )

        return self._build_homework_response(homework)

    async def list_homework(
        self,
        current_user: CurrentUser,
        record_date: Optional[date],
        standard_id: Optional[uuid.UUID],
        subject_id: Optional[uuid.UUID],
        academic_year_id: Optional[uuid.UUID],
        is_submitted: Optional[bool],
        page: int,
        page_size: int,
    ) -> HomeworkListResponse:
        school_id = self._ensure_school(current_user)

        resolved_date = record_date
        resolved_year_id = academic_year_id
        if not resolved_year_id:
            resolved_year_id = (await get_active_year(school_id, self.db)).id

        teacher_id_filter: Optional[uuid.UUID] = None
        standard_ids_filter: Optional[list[uuid.UUID]] = None
        resolved_standard_id: Optional[uuid.UUID] = standard_id
        submission_student_ids: Optional[list[uuid.UUID]] = None

        from app.models.student import Student

        if current_user.role == RoleEnum.TEACHER:
            teacher_id_filter = await _get_teacher_id(
                self.db, current_user.id, school_id
            )

        elif current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.standard_id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_standard_id = result.scalar_one_or_none()
            if not own_standard_id:
                raise ForbiddenException("Student profile not found or class not assigned")
            if standard_id and standard_id != own_standard_id:
                raise ForbiddenException("You can only view homework for your own class")
            standard_ids_filter = [own_standard_id]
            resolved_standard_id = None
            student = await self.student_repo.get_by_user_id(current_user.id)
            submission_student_ids = [student.id] if student else []

        elif current_user.role == RoleEnum.PARENT:
            if standard_id:
                result = await self.db.execute(
                    select(Student.id).where(
                        and_(
                            Student.standard_id == standard_id,
                            Student.parent_id == current_user.parent_id,
                            Student.school_id == school_id,
                        )
                    )
                )
                if not result.scalar_one_or_none():
                    raise ForbiddenException("You do not have a child in this class")
                standard_ids_filter = [standard_id]
                resolved_standard_id = None
                child_result = await self.db.execute(
                    select(Student.id).where(
                        and_(
                            Student.standard_id == standard_id,
                            Student.parent_id == current_user.parent_id,
                            Student.school_id == school_id,
                        )
                    )
                )
                submission_student_ids = [row[0] for row in child_result.all()]
            else:
                result = await self.db.execute(
                    select(Student.standard_id).where(
                        and_(
                            Student.parent_id == current_user.parent_id,
                            Student.school_id == school_id,
                        )
                    )
                )
                standard_ids = [row[0] for row in result.all() if row[0] is not None]
                standard_ids_filter = list(dict.fromkeys(standard_ids))
                resolved_standard_id = None
                child_ids_result = await self.db.execute(
                    select(Student.id).where(
                        and_(
                            Student.parent_id == current_user.parent_id,
                            Student.school_id == school_id,
                        )
                    )
                )
                submission_student_ids = [row[0] for row in child_ids_result.all()]

        items, total = await self.repo.list_by_school(
            school_id=school_id,
            standard_id=resolved_standard_id,
            standard_ids=standard_ids_filter,
            subject_id=subject_id,
            record_date=resolved_date,
            academic_year_id=resolved_year_id,
            teacher_id=teacher_id_filter,
            is_submitted=is_submitted,
            submission_student_ids=submission_student_ids,
            page=page,
            page_size=page_size,
        )

        submitted_homework_ids: set[uuid.UUID] = set()
        if current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT):
            if submission_student_ids is None:
                submission_student_ids = []
            if submission_student_ids and items:
                hw_ids = [h.id for h in items]
                sub_rows = await self.db.execute(
                    select(HomeworkSubmission.homework_id).where(
                        and_(
                            HomeworkSubmission.school_id == school_id,
                            HomeworkSubmission.homework_id.in_(hw_ids),
                            HomeworkSubmission.student_id.in_(submission_student_ids),
                        )
                    )
                )
                submitted_homework_ids = {row[0] for row in sub_rows.all()}

        return HomeworkListResponse(
            items=[
                self._build_homework_response(
                    h,
                    is_submitted=(
                        h.id in submitted_homework_ids
                        if current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT)
                        else None
                    ),
                )
                for h in items
            ],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    def _build_submission_response(self, submission) -> HomeworkSubmissionResponse:
        data = HomeworkSubmissionResponse.model_validate(submission)
        if getattr(submission, "file_key", None):
            data.file_url = minio_client.generate_presigned_url(
                HOMEWORK_RESPONSE_BUCKET, submission.file_key
            )
        student = getattr(submission, "student", None)
        if student is not None:
            data.student_admission_number = student.admission_number
            data.student_name = (
                (student.user.email if student.user else None)
                or (student.user.phone if student.user else None)
                or student.admission_number
            )
        performer = getattr(submission, "performer", None)
        if performer is not None:
            data.performer_name = performer.email or performer.phone
        reviewer = getattr(submission, "reviewer", None)
        if reviewer is not None:
            data.reviewer_name = reviewer.email or reviewer.phone
        return data

    async def create_submission(
        self,
        body: HomeworkSubmissionCreate,
        current_user: CurrentUser,
        file: Optional[UploadFile] = None,
    ) -> HomeworkSubmissionResponse:
        school_id = self._ensure_school(current_user)

        if current_user.role not in (RoleEnum.STUDENT, RoleEnum.PARENT):
            raise ForbiddenException("Only students/parents can submit homework responses")

        homework = await self.repo.get_by_id(body.homework_id, school_id)
        if not homework:
            raise NotFoundException("Homework not found")

        student_id: Optional[uuid.UUID] = None
        if current_user.role == RoleEnum.STUDENT:
            student = await self.student_repo.get_by_user_id(current_user.id)
            if not student or student.school_id != school_id:
                raise ForbiddenException("Student profile not found")
            student_id = student.id
        else:
            if not body.student_id:
                raise ValidationException("student_id is required for parent submissions")
            student = await self.student_repo.get_by_id(body.student_id, school_id)
            if not student or student.parent_id != current_user.parent_id:
                raise ForbiddenException("Not your child")
            student_id = body.student_id

        student = await self.student_repo.get_by_id(student_id, school_id)
        if not student:
            raise NotFoundException("Student not found")
        if student.standard_id != homework.standard_id:
            raise ForbiddenException("Homework does not belong to this student's class")

        existing = await self.submission_repo.get_existing(
            homework_id=homework.id,
            student_id=student_id,
            school_id=school_id,
        )
        if existing:
            raise ConflictException("Homework response already submitted for this student")

        text_response = body.text_response.strip() if body.text_response else ""
        file_key: Optional[str] = None
        if file and file.filename:
            content = await file.read()
            if not content:
                raise ValidationException("Uploaded homework response file is empty")
            file_key = (
                f"{school_id}/{homework.id}/{student_id}/"
                f"{uuid.uuid4()}_{file.filename}"
            )
            minio_client.upload_file(
                bucket=HOMEWORK_RESPONSE_BUCKET,
                key=file_key,
                file_bytes=content,
                content_type=file.content_type or "application/octet-stream",
            )
        if not text_response and file_key is None:
            raise ValidationException("Provide response text or attach a file")

        submission = await self.submission_repo.create(
            {
                "homework_id": homework.id,
                "student_id": student_id,
                "performed_by": current_user.id,
                "text_response": text_response,
                "file_key": file_key,
                "school_id": school_id,
            }
        )
        await self.db.refresh(submission)
        hydrated = await self.submission_repo.get_by_id(submission.id, school_id)
        return self._build_submission_response(hydrated or submission)

    async def list_submissions(
        self,
        homework_id: uuid.UUID,
        current_user: CurrentUser,
        student_id: Optional[uuid.UUID],
        page: int,
        page_size: int,
    ) -> HomeworkSubmissionListResponse:
        school_id = self._ensure_school(current_user)
        homework = await self.repo.get_by_id(homework_id, school_id)
        if not homework:
            raise NotFoundException("Homework not found")

        effective_student_id = student_id
        effective_parent_id: Optional[uuid.UUID] = None

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
            if homework.teacher_id != teacher_id:
                raise ForbiddenException(
                    "You can only view responses for your own homework"
                )
        elif current_user.role == RoleEnum.STUDENT:
            student = await self.student_repo.get_by_user_id(current_user.id)
            if not student or student.school_id != school_id:
                raise ForbiddenException("Student profile not found")
            effective_student_id = student.id
        elif current_user.role == RoleEnum.PARENT:
            effective_parent_id = current_user.parent_id
            effective_student_id = None if student_id is None else student_id
            if student_id is not None:
                student = await self.student_repo.get_by_id(student_id, school_id)
                if not student or student.parent_id != current_user.parent_id:
                    raise ForbiddenException("Not your child")
        else:
            raise ForbiddenException("Not allowed")

        items, total = await self.submission_repo.list_by_homework(
            homework_id=homework_id,
            school_id=school_id,
            student_id=effective_student_id,
            parent_id=effective_parent_id,
            page=page,
            page_size=page_size,
        )
        return HomeworkSubmissionListResponse(
            items=[self._build_submission_response(s) for s in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    async def review_submission(
        self,
        submission_id: uuid.UUID,
        body: HomeworkSubmissionReview,
        current_user: CurrentUser,
    ) -> HomeworkSubmissionResponse:
        school_id = self._ensure_school(current_user)
        if current_user.role != RoleEnum.TEACHER:
            raise ForbiddenException("Only teachers can review homework responses")

        submission = await self.submission_repo.get_by_id(submission_id, school_id)
        if not submission:
            raise NotFoundException("Homework response not found")

        homework = await self.repo.get_by_id(submission.homework_id, school_id)
        if not homework:
            raise NotFoundException("Homework not found")
        teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
        if homework.teacher_id != teacher_id:
            raise ForbiddenException("You can only review responses for your own homework")

        if body.feedback is None and body.is_approved is None:
            raise ValidationException(
                "Provide at least one review field: feedback or is_approved"
            )

        updated = await self.submission_repo.update(
            submission,
            {
                "feedback": body.feedback if body.feedback is not None else submission.feedback,
                "is_approved": (
                    body.is_approved
                    if body.is_approved is not None
                    else submission.is_approved
                ),
                "is_reviewed": True,
                "reviewed_by": current_user.id,
                "reviewed_at": datetime.now(tz=timezone.utc),
            },
        )
        await self.db.refresh(updated)
        hydrated = await self.submission_repo.get_by_id(updated.id, school_id)
        return self._build_submission_response(hydrated or updated)

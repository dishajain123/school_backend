# 🆕 NEW FILE
# app/services/my_class.py
"""
My Class service layer.

Responsibilities:
  1. Access control (teacher assignment check, student enrollment check, parent-child check)
  2. Academic year isolation (current = full access, past = read-only, quiz locked)
  3. Presigned URL generation for file-type ContentItems (decision #2)
  4. Quiz grading logic
  5. Multiple attempts (decision #3) with current-year enforcement

Access control design:
  - Reuses TeacherClassSubjectService.assert_teacher_owns_class_subject()
  - Student access validated against StudentYearMapping
  - Parent access: validates parent owns child, then delegates to student path
  - Admin/Principal: read-only everywhere

section_id ↔ TeacherClassSubject.section (string):
  - Decision #1: Chapter stores section_id (UUID FK)
  - TeacherClassSubject stores section as a plain string (e.g. "A")
  - Bridge: we load Section by section_id → get section.name → compare with assignment.section
"""

import uuid
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
    ConflictException,
)
from app.integrations.minio_client import generate_presigned_url, upload_file  # existing helper
from app.models.academic_year import AcademicYear
from app.models.my_class import (
    Attempt,
    Chapter,
    ContentItem,
    Question,
    Quiz,
    Topic,
)
from app.models.section import Section
from app.models.student import Student
from app.models.student_year_mapping import StudentYearMapping
from app.repositories.my_class import (
    AttemptRepository,
    ChapterRepository,
    ContentItemRepository,
    QuestionRepository,
    QuizRepository,
    TopicRepository,
)
from app.schemas.my_class import (
    AttemptCreate,
    AttemptListResponse,
    AttemptResponse,
    AttemptResultResponse,
    ChapterCreate,
    ChapterListResponse,
    ChapterResponse,
    ChapterUpdate,
    ContentItemCreate,
    ContentItemListResponse,
    ContentItemResponse,
    ContentItemUpdate,
    QuestionCreate,
    QuestionResponse,
    QuestionUpdate,
    QuizCreate,
    QuizPublicResponse,
    QuizResponse,
    QuizUpdate,
    QuizWithQuestionsResponse,
    SubjectListForClassResponse,
    SubjectSummaryForClass,
    TopicCreate,
    TopicListResponse,
    TopicResponse,
    TopicUpdate,
)
from app.services.teacher_class_subject import TeacherClassSubjectService
from app.utils.enums import RoleEnum

# MinIO bucket for My Class files
_MY_CLASS_BUCKET = "my-class"
# Presigned URL expiry seconds (1 hour)
_PRESIGNED_EXPIRY = 3600


class MyClassService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chapter_repo = ChapterRepository(db)
        self.topic_repo = TopicRepository(db)
        self.content_repo = ContentItemRepository(db)
        self.quiz_repo = QuizRepository(db)
        self.question_repo = QuestionRepository(db)
        self.attempt_repo = AttemptRepository(db)
        self._tcs_service = TeacherClassSubjectService(db)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _require_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def _get_section_name(self, section_id: uuid.UUID) -> str:
        """Resolve section.name from section_id for TeacherClassSubject comparison."""
        result = await self.db.execute(
            select(Section).where(Section.id == section_id)
        )
        section = result.scalar_one_or_none()
        if not section:
            raise NotFoundException("Section not found")
        return section.name  # e.g. "A", "B"

    async def _load_academic_year(self, year_id: uuid.UUID) -> AcademicYear:
        result = await self.db.execute(
            select(AcademicYear).where(AcademicYear.id == year_id)
        )
        year = result.scalar_one_or_none()
        if not year:
            raise NotFoundException("Academic year not found")
        return year

    def _is_current_year(self, year: AcademicYear) -> bool:
        """Current year = is_active flag on AcademicYear."""
        return bool(getattr(year, "is_active", False))

    async def _assert_write_allowed(self, academic_year_id: uuid.UUID) -> None:
        """Raises if the year is historical (read-only)."""
        year = await self._load_academic_year(academic_year_id)
        if not self._is_current_year(year):
            raise ForbiddenException(
                "This academic year is read-only. Content can only be modified in the current year."
            )

    def _assert_teacher_write_role(self, current_user: CurrentUser) -> None:
        if current_user.role != RoleEnum.TEACHER:
            raise ForbiddenException("Only teachers can create or modify classroom content")

    async def _assert_teacher_access(
        self,
        current_user: CurrentUser,
        standard_id: uuid.UUID,
        section_id: uuid.UUID,
        subject_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> None:
        """
        Validates the calling teacher is assigned to this class/section/subject/year.
        Bridges section_id (UUID) → section.name → TeacherClassSubject.section (string).
        """
        teacher_result = await self.db.execute(
            select(__import__('app.models.teacher', fromlist=['Teacher']).Teacher)
            .where(
                __import__('app.models.teacher', fromlist=['Teacher']).Teacher.user_id == current_user.id
            )
        )
        teacher = teacher_result.scalar_one_or_none()
        if not teacher:
            raise ForbiddenException("Teacher profile not found")

        section_name = await self._get_section_name(section_id)
        await self._tcs_service.assert_teacher_owns_class_subject(
            teacher_id=teacher.id,
            standard_id=standard_id,
            subject_id=subject_id,
            academic_year_id=academic_year_id,
            section=section_name,
        )

    async def _resolve_teacher(self, user_id: uuid.UUID):
        """Load teacher profile from user_id."""
        from app.models.teacher import Teacher  # local import to avoid circular
        result = await self.db.execute(
            select(Teacher).where(Teacher.user_id == user_id)
        )
        teacher = result.scalar_one_or_none()
        if not teacher:
            raise ForbiddenException("Teacher profile not found for this user")
        return teacher

    async def _assert_student_enrollment(
        self,
        student_id: uuid.UUID,
        standard_id: uuid.UUID,
        section_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> None:
        """Validates student is enrolled in the given class/section/year."""
        result = await self.db.execute(
            select(StudentYearMapping).where(
                StudentYearMapping.student_id == student_id,
                StudentYearMapping.standard_id == standard_id,
                StudentYearMapping.section_id == section_id,
                StudentYearMapping.academic_year_id == academic_year_id,
                StudentYearMapping.school_id == school_id,
            )
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            raise ForbiddenException(
                "Student is not enrolled in this class/section for the given academic year"
            )

    async def _get_student_by_user(
        self,
        user_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> Student:
        result = await self.db.execute(
            select(Student).where(
                Student.user_id == user_id,
                Student.school_id == school_id,
            )
        )
        student = result.scalar_one_or_none()
        if not student:
            raise NotFoundException("Student profile not found")
        return student

    async def _assert_parent_owns_child(
        self,
        parent_user_id: uuid.UUID,
        child_student_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> None:
        """Validates parent → child relationship using existing parent model."""
        from app.models.parent import Parent  # local import
        parent_result = await self.db.execute(
            select(Parent).where(
                Parent.user_id == parent_user_id,
                Parent.school_id == school_id,
            )
        )
        parent = parent_result.scalar_one_or_none()
        if not parent:
            raise ForbiddenException("Parent profile not found")

        student_result = await self.db.execute(
            select(Student).where(
                Student.id == child_student_id,
                Student.parent_id == parent.id,
                Student.school_id == school_id,
            )
        )
        child = student_result.scalar_one_or_none()
        if not child:
            raise ForbiddenException("This student is not linked to your parent profile")

    async def _resolve_student_id_for_role(
        self,
        current_user: CurrentUser,
        school_id: uuid.UUID,
        child_id: Optional[uuid.UUID],
    ) -> uuid.UUID:
        """
        Returns the student_id to use for read operations based on the caller's role.
        - STUDENT: own student_id
        - PARENT: child_id (decision #4 — ?child_id= query param, parent ownership validated)
        """
        if current_user.role == RoleEnum.STUDENT:
            student = await self._get_student_by_user(current_user.id, school_id)
            return student.id
        elif current_user.role == RoleEnum.PARENT:
            if not child_id:
                raise ValidationException(
                    "child_id query parameter is required for parent access"
                )
            await self._assert_parent_owns_child(current_user.id, child_id, school_id)
            return child_id
        else:
            raise ForbiddenException("Role not permitted for this operation")

    async def _inject_presigned_url(
        self,
        item: ContentItem,
    ) -> ContentItemResponse:
        """Build ContentItemResponse and inject presigned URL for file items."""
        resp = ContentItemResponse.model_validate(item)
        if item.content_type == "file" and item.file_key:
            try:
                url = await generate_presigned_url(
                    bucket=_MY_CLASS_BUCKET,
                    key=item.file_key,
                    expiry=_PRESIGNED_EXPIRY,
                )
                resp = resp.model_copy(update={"file_url": url})
            except Exception:
                # Non-fatal — client can retry; don't break the response
                pass
        return resp

    async def _build_chapter_response(self, chapter: Chapter) -> ChapterResponse:
        topic_count = await self.chapter_repo.count_topics(chapter.id)
        resp = ChapterResponse.model_validate(chapter)
        return resp.model_copy(update={"topic_count": topic_count})

    async def _build_topic_response(self, topic: Topic) -> TopicResponse:
        content_count = await self.topic_repo.count_content(topic.id)
        resp = TopicResponse.model_validate(topic)
        return resp.model_copy(update={"content_count": content_count})

    async def _build_quiz_response(
        self,
        quiz: Quiz,
        include_answers: bool = False,
    ) -> QuizResponse:
        question_count = await self.quiz_repo.count_questions(quiz.id)
        questions = await self.question_repo.list_by_quiz(quiz.id)

        if include_answers:
            q_list = [QuestionResponse.model_validate(q) for q in questions]  # type: ignore[arg-type]
            resp = QuizWithQuestionsResponse.model_validate(quiz)
            return resp.model_copy(update={"question_count": question_count, "questions": q_list})
        else:
            from app.schemas.my_class import QuestionPublicResponse
            q_list = [QuestionPublicResponse.model_validate(q) for q in questions]  # type: ignore[arg-type]
            resp = QuizPublicResponse.model_validate(quiz)
            return resp.model_copy(update={"question_count": question_count, "questions": q_list})

    # ─────────────────────────────────────────────────────────────────────────
    # Subject listing (student / parent entry point)
    # ─────────────────────────────────────────────────────────────────────────

    async def list_subjects_for_class(
        self,
        standard_id: uuid.UUID,
        section_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        current_user: CurrentUser,
        child_id: Optional[uuid.UUID] = None,
    ) -> SubjectListForClassResponse:
        """
        Returns subjects that have teacher assignments for a given class/section/year.
        Access: STUDENT (own enrollment validated), PARENT (child_id param), TEACHER, ADMIN.
        """
        school_id = self._require_school(current_user)

        # Access control
        if current_user.role == RoleEnum.STUDENT:
            student = await self._get_student_by_user(current_user.id, school_id)
            await self._assert_student_enrollment(
                student.id, standard_id, section_id, academic_year_id, school_id
            )
        elif current_user.role == RoleEnum.PARENT:
            student_id = await self._resolve_student_id_for_role(current_user, school_id, child_id)
            await self._assert_student_enrollment(
                student_id, standard_id, section_id, academic_year_id, school_id
            )
        elif current_user.role == RoleEnum.TEACHER:
            pass  # Teacher sees all subjects they are assigned to; filtered below
        # Admin / Principal: unrestricted

        section_name = await self._get_section_name(section_id)

        # Load teacher-class-subject assignments for this class/section/year
        from app.models.teacher_class_subject import TeacherClassSubject
        from app.models.masters import Subject
        from app.models.user import User
        from app.models.teacher import Teacher

        stmt = (
            select(TeacherClassSubject)
            .where(
                TeacherClassSubject.standard_id == standard_id,
                TeacherClassSubject.section == section_name,
                TeacherClassSubject.academic_year_id == academic_year_id,
            )
        )
        rows = await self.db.execute(stmt)
        assignments = list(rows.scalars().all())

        items: list[SubjectSummaryForClass] = []
        for asgn in assignments:
            # Load subject
            sub_result = await self.db.execute(
                select(Subject).where(Subject.id == asgn.subject_id)
            )
            subject = sub_result.scalar_one_or_none()
            if not subject:
                continue

            # Load teacher name
            teacher_name: Optional[str] = None
            teacher_result = await self.db.execute(
                select(Teacher).where(Teacher.id == asgn.teacher_id)
            )
            teacher = teacher_result.scalar_one_or_none()
            if teacher:
                user_result = await self.db.execute(
                    select(User).where(User.id == teacher.user_id)
                )
                user = user_result.scalar_one_or_none()
                if user:
                    teacher_name = getattr(user, "full_name", None)

            # Count chapters
            _, chapter_count = await self.chapter_repo.list_by_subject(
                school_id=school_id,
                subject_id=subject.id,
                standard_id=standard_id,
                section_id=section_id,
                academic_year_id=academic_year_id,
            )

            items.append(
                SubjectSummaryForClass(
                    subject_id=subject.id,
                    subject_name=subject.name,
                    subject_code=subject.code,
                    standard_id=standard_id,
                    section_id=section_id,
                    academic_year_id=academic_year_id,
                    teacher_name=teacher_name,
                    chapter_count=chapter_count,
                )
            )

        return SubjectListForClassResponse(items=items, total=len(items))

    # ─────────────────────────────────────────────────────────────────────────
    # Chapter CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def create_chapter(
        self,
        payload: ChapterCreate,
        current_user: CurrentUser,
    ) -> ChapterResponse:
        school_id = self._require_school(current_user)
        self._assert_teacher_write_role(current_user)
        await self._assert_write_allowed(payload.academic_year_id)
        await self._assert_teacher_access(
                current_user,
                standard_id=payload.standard_id,
                section_id=payload.section_id,
                subject_id=payload.subject_id,
                academic_year_id=payload.academic_year_id,
            )

        chapter = await self.chapter_repo.create({
            "school_id": school_id,
            "subject_id": payload.subject_id,
            "standard_id": payload.standard_id,
            "section_id": payload.section_id,
            "academic_year_id": payload.academic_year_id,
            "created_by": current_user.id,
            "title": payload.title,
            "description": payload.description,
            "order_index": payload.order_index,
        })
        return await self._build_chapter_response(chapter)

    async def list_chapters(
        self,
        subject_id: uuid.UUID,
        standard_id: uuid.UUID,
        section_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        current_user: CurrentUser,
        child_id: Optional[uuid.UUID] = None,
    ) -> ChapterListResponse:
        school_id = self._require_school(current_user)

        if current_user.role == RoleEnum.STUDENT:
            student = await self._get_student_by_user(current_user.id, school_id)
            await self._assert_student_enrollment(
                student.id, standard_id, section_id, academic_year_id, school_id
            )
        elif current_user.role == RoleEnum.PARENT:
            student_id = await self._resolve_student_id_for_role(current_user, school_id, child_id)
            await self._assert_student_enrollment(
                student_id, standard_id, section_id, academic_year_id, school_id
            )
        elif current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_access(
                current_user, standard_id, section_id, subject_id, academic_year_id
            )

        chapters, total = await self.chapter_repo.list_by_subject(
            school_id=school_id,
            subject_id=subject_id,
            standard_id=standard_id,
            section_id=section_id,
            academic_year_id=academic_year_id,
        )
        items = [await self._build_chapter_response(c) for c in chapters]
        return ChapterListResponse(items=items, total=total)

    async def update_chapter(
        self,
        chapter_id: uuid.UUID,
        payload: ChapterUpdate,
        current_user: CurrentUser,
    ) -> ChapterResponse:
        school_id = self._require_school(current_user)
        chapter = await self.chapter_repo.get_by_id(chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")

        self._assert_teacher_write_role(current_user)
        await self._assert_write_allowed(chapter.academic_year_id)
        await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )

        update_data = payload.model_dump(exclude_none=True)
        chapter = await self.chapter_repo.update(chapter, update_data)
        return await self._build_chapter_response(chapter)

    async def delete_chapter(
        self,
        chapter_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> None:
        school_id = self._require_school(current_user)
        chapter = await self.chapter_repo.get_by_id(chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")

        self._assert_teacher_write_role(current_user)
        await self._assert_write_allowed(chapter.academic_year_id)
        await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )

        await self.chapter_repo.delete(chapter)

    # ─────────────────────────────────────────────────────────────────────────
    # Topic CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def _load_chapter_for_teacher(
        self,
        chapter_id: uuid.UUID,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Chapter:
        chapter = await self.chapter_repo.get_by_id(chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")
        if current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )
        return chapter

    async def create_topic(
        self,
        payload: TopicCreate,
        current_user: CurrentUser,
    ) -> TopicResponse:
        school_id = self._require_school(current_user)
        self._assert_teacher_write_role(current_user)
        chapter = await self._load_chapter_for_teacher(
            payload.chapter_id, school_id, current_user
        )
        await self._assert_write_allowed(chapter.academic_year_id)

        topic = await self.topic_repo.create({
            "chapter_id": payload.chapter_id,
            "created_by": current_user.id,
            "title": payload.title,
            "description": payload.description,
            "order_index": payload.order_index,
        })
        return await self._build_topic_response(topic)

    async def list_topics(
        self,
        chapter_id: uuid.UUID,
        current_user: CurrentUser,
        child_id: Optional[uuid.UUID] = None,
    ) -> TopicListResponse:
        school_id = self._require_school(current_user)
        chapter = await self.chapter_repo.get_by_id(chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")

        if current_user.role == RoleEnum.STUDENT:
            student = await self._get_student_by_user(current_user.id, school_id)
            await self._assert_student_enrollment(
                student.id,
                chapter.standard_id,
                chapter.section_id,
                chapter.academic_year_id,
                school_id,
            )
        elif current_user.role == RoleEnum.PARENT:
            student_id = await self._resolve_student_id_for_role(current_user, school_id, child_id)
            await self._assert_student_enrollment(
                student_id,
                chapter.standard_id,
                chapter.section_id,
                chapter.academic_year_id,
                school_id,
            )
        elif current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )

        topics, total = await self.topic_repo.list_by_chapter(chapter_id)
        items = [await self._build_topic_response(t) for t in topics]
        return TopicListResponse(items=items, total=total)

    async def update_topic(
        self,
        topic_id: uuid.UUID,
        payload: TopicUpdate,
        current_user: CurrentUser,
    ) -> TopicResponse:
        school_id = self._require_school(current_user)
        topic = await self.topic_repo.get_by_id(topic_id)
        if not topic:
            raise NotFoundException("Topic not found")

        chapter = await self.chapter_repo.get_by_id(topic.chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")

        self._assert_teacher_write_role(current_user)
        await self._assert_write_allowed(chapter.academic_year_id)
        await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )

        update_data = payload.model_dump(exclude_none=True)
        topic = await self.topic_repo.update(topic, update_data)
        return await self._build_topic_response(topic)

    async def delete_topic(
        self,
        topic_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> None:
        school_id = self._require_school(current_user)
        topic = await self.topic_repo.get_by_id(topic_id)
        if not topic:
            raise NotFoundException("Topic not found")

        chapter = await self.chapter_repo.get_by_id(topic.chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")

        self._assert_teacher_write_role(current_user)
        await self._assert_write_allowed(chapter.academic_year_id)
        await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )

        await self.topic_repo.delete(topic)

    # ─────────────────────────────────────────────────────────────────────────
    # ContentItem CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def add_content(
        self,
        payload: ContentItemCreate,
        current_user: CurrentUser,
    ) -> ContentItemResponse:
        school_id = self._require_school(current_user)
        self._assert_teacher_write_role(current_user)
        await self._assert_write_allowed(payload.academic_year_id)
        await self._assert_teacher_access(
                current_user,
                standard_id=payload.standard_id,
                section_id=payload.section_id,
                subject_id=payload.subject_id,
                academic_year_id=payload.academic_year_id,
            )

        item = await self.content_repo.create({
            "topic_id": payload.topic_id,
            "created_by": current_user.id,
            "academic_year_id": payload.academic_year_id,
            "standard_id": payload.standard_id,
            "section_id": payload.section_id,
            "subject_id": payload.subject_id,
            "school_id": school_id,
            "content_type": payload.content_type,
            "title": payload.title,
            "order_index": payload.order_index,
            "metadata_json": payload.metadata_json,
            "note_text": payload.note_text,
            "file_key": payload.file_key,
            "file_name": payload.file_name,
            "file_mime_type": payload.file_mime_type,
            "link_url": payload.link_url,
            "link_title": payload.link_title,
            "quiz_id": payload.quiz_id,
        })
        return await self._inject_presigned_url(item)

    async def upload_content_file(
        self,
        *,
        current_user: CurrentUser,
        standard_id: uuid.UUID,
        section_id: uuid.UUID,
        subject_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
    ) -> dict[str, str]:
        school_id = self._require_school(current_user)
        self._assert_teacher_write_role(current_user)
        await self._assert_write_allowed(academic_year_id)
        await self._assert_teacher_access(
            current_user,
            standard_id=standard_id,
            section_id=section_id,
            subject_id=subject_id,
            academic_year_id=academic_year_id,
        )

        safe_name = (file_name or "classroom_file").replace("/", "_").replace("\\", "_")
        key = (
            f"{school_id}/{academic_year_id}/{standard_id}/{section_id}/"
            f"{subject_id}/{uuid.uuid4()}_{safe_name}"
        )
        upload_file(
            bucket=_MY_CLASS_BUCKET,
            key=key,
            file_bytes=file_bytes,
            content_type=content_type or "application/octet-stream",
        )
        return {
            "file_key": key,
            "file_name": safe_name,
            "file_mime_type": content_type or "application/octet-stream",
        }

    async def list_content(
        self,
        topic_id: uuid.UUID,
        current_user: CurrentUser,
        child_id: Optional[uuid.UUID] = None,
    ) -> ContentItemListResponse:
        school_id = self._require_school(current_user)
        topic = await self.topic_repo.get_by_id(topic_id)
        if not topic:
            raise NotFoundException("Topic not found")

        chapter = await self.chapter_repo.get_by_id(topic.chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")

        if current_user.role == RoleEnum.STUDENT:
            student = await self._get_student_by_user(current_user.id, school_id)
            await self._assert_student_enrollment(
                student.id,
                chapter.standard_id,
                chapter.section_id,
                chapter.academic_year_id,
                school_id,
            )
        elif current_user.role == RoleEnum.PARENT:
            student_id = await self._resolve_student_id_for_role(current_user, school_id, child_id)
            await self._assert_student_enrollment(
                student_id,
                chapter.standard_id,
                chapter.section_id,
                chapter.academic_year_id,
                school_id,
            )
        elif current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )

        items_raw, total = await self.content_repo.list_by_topic(topic_id, school_id)
        items = [await self._inject_presigned_url(i) for i in items_raw]
        return ContentItemListResponse(items=items, total=total)

    async def update_content(
        self,
        item_id: uuid.UUID,
        payload: ContentItemUpdate,
        current_user: CurrentUser,
    ) -> ContentItemResponse:
        school_id = self._require_school(current_user)
        item = await self.content_repo.get_by_id(item_id, school_id)
        if not item:
            raise NotFoundException("Content item not found")

        self._assert_teacher_write_role(current_user)
        await self._assert_write_allowed(item.academic_year_id)
        await self._assert_teacher_access(
                current_user,
                standard_id=item.standard_id,
                section_id=item.section_id,
                subject_id=item.subject_id,
                academic_year_id=item.academic_year_id,
            )

        update_data = payload.model_dump(exclude_none=True)
        item = await self.content_repo.update(item, update_data)
        return await self._inject_presigned_url(item)

    async def delete_content(
        self,
        item_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> None:
        school_id = self._require_school(current_user)
        item = await self.content_repo.get_by_id(item_id, school_id)
        if not item:
            raise NotFoundException("Content item not found")

        self._assert_teacher_write_role(current_user)
        await self._assert_write_allowed(item.academic_year_id)
        await self._assert_teacher_access(
                current_user,
                standard_id=item.standard_id,
                section_id=item.section_id,
                subject_id=item.subject_id,
                academic_year_id=item.academic_year_id,
            )

        await self.content_repo.delete(item)

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def _load_topic_for_write(
        self,
        topic_id: uuid.UUID,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Topic:
        topic = await self.topic_repo.get_by_id(topic_id)
        if not topic:
            raise NotFoundException("Topic not found")
        chapter = await self.chapter_repo.get_by_id(topic.chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")
        if current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )
        await self._assert_write_allowed(chapter.academic_year_id)
        return topic

    async def create_quiz(
        self,
        payload: QuizCreate,
        current_user: CurrentUser,
    ) -> QuizWithQuestionsResponse:
        school_id = self._require_school(current_user)
        self._assert_teacher_write_role(current_user)
        await self._load_topic_for_write(payload.topic_id, school_id, current_user)

        quiz = await self.quiz_repo.create({
            "topic_id": payload.topic_id,
            "school_id": school_id,
            "created_by": current_user.id,
            "title": payload.title,
            "instructions": payload.instructions,
            "total_marks": payload.total_marks,
            "duration_minutes": payload.duration_minutes,
        })
        return await self._build_quiz_response(quiz, include_answers=True)  # type: ignore[return-value]

    async def get_quiz(
        self,
        quiz_id: uuid.UUID,
        current_user: CurrentUser,
        child_id: Optional[uuid.UUID] = None,
    ) -> QuizResponse:
        school_id = self._require_school(current_user)
        quiz = await self.quiz_repo.get_by_id(quiz_id, school_id)
        if not quiz:
            raise NotFoundException("Quiz not found")

        topic = await self.topic_repo.get_by_id(quiz.topic_id)
        if not topic:
            raise NotFoundException("Topic not found")
        chapter = await self.chapter_repo.get_by_id(topic.chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")

        if current_user.role == RoleEnum.TEACHER:
            await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )
        elif current_user.role == RoleEnum.STUDENT:
            student = await self._get_student_by_user(current_user.id, school_id)
            await self._assert_student_enrollment(
                student.id,
                chapter.standard_id,
                chapter.section_id,
                chapter.academic_year_id,
                school_id,
            )
        elif current_user.role == RoleEnum.PARENT:
            student_id = await self._resolve_student_id_for_role(
                current_user, school_id, child_id
            )
            await self._assert_student_enrollment(
                student_id,
                chapter.standard_id,
                chapter.section_id,
                chapter.academic_year_id,
                school_id,
            )
        elif current_user.role not in (
            RoleEnum.PRINCIPAL,
            RoleEnum.SUPERADMIN,
            RoleEnum.TRUSTEE,
            RoleEnum.STAFF_ADMIN,
        ):
            raise ForbiddenException("Role not permitted to view this quiz")

        include_answers = current_user.role in (
            RoleEnum.TEACHER,
            RoleEnum.PRINCIPAL,
            RoleEnum.SUPERADMIN,
            RoleEnum.TRUSTEE,
            RoleEnum.STAFF_ADMIN,
        )
        return await self._build_quiz_response(quiz, include_answers=include_answers)

    async def update_quiz(
        self,
        quiz_id: uuid.UUID,
        payload: QuizUpdate,
        current_user: CurrentUser,
    ) -> QuizWithQuestionsResponse:
        school_id = self._require_school(current_user)
        self._assert_teacher_write_role(current_user)
        quiz = await self.quiz_repo.get_by_id(quiz_id, school_id)
        if not quiz:
            raise NotFoundException("Quiz not found")

        await self._load_topic_for_write(quiz.topic_id, school_id, current_user)

        update_data = payload.model_dump(exclude_none=True)
        quiz = await self.quiz_repo.update(quiz, update_data)
        return await self._build_quiz_response(quiz, include_answers=True)  # type: ignore[return-value]

    # ─────────────────────────────────────────────────────────────────────────
    # Question CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def add_question(
        self,
        payload: QuestionCreate,
        current_user: CurrentUser,
    ) -> QuestionResponse:
        school_id = self._require_school(current_user)
        self._assert_teacher_write_role(current_user)
        quiz = await self.quiz_repo.get_by_id(payload.quiz_id, school_id)
        if not quiz:
            raise NotFoundException("Quiz not found")

        await self._load_topic_for_write(quiz.topic_id, school_id, current_user)

        question = await self.question_repo.create({
            "quiz_id": payload.quiz_id,
            "question_text": payload.question_text,
            "question_type": payload.question_type,
            "options_json": payload.options_json,
            "correct_answer": payload.correct_answer,
            "marks": payload.marks,
            "explanation": payload.explanation,
            "order_index": payload.order_index,
        })
        # 🔥 NEW: auto-update quiz total_marks
        questions = await self.question_repo.list_by_quiz(payload.quiz_id)
        total = sum(q.marks for q in questions)
        await self.quiz_repo.update(quiz, {"total_marks": total})
        return QuestionResponse.model_validate(question)

    async def update_question(
        self,
        question_id: uuid.UUID,
        payload: QuestionUpdate,
        current_user: CurrentUser,
    ) -> QuestionResponse:
        school_id = self._require_school(current_user)
        self._assert_teacher_write_role(current_user)
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundException("Question not found")

        quiz = await self.quiz_repo.get_by_id(question.quiz_id, school_id)
        if not quiz:
            raise NotFoundException("Quiz not found")

        await self._load_topic_for_write(quiz.topic_id, school_id, current_user)

        update_data = payload.model_dump(exclude_none=True)
        question = await self.question_repo.update(question, update_data)

        # Recalculate total_marks after marks change
        questions = await self.question_repo.list_by_quiz(quiz.id)
        total = sum(q.marks for q in questions)
        await self.quiz_repo.update(quiz, {"total_marks": total})
        return QuestionResponse.model_validate(question)

    async def delete_question(
        self,
        question_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> None:
        school_id = self._require_school(current_user)
        self._assert_teacher_write_role(current_user)
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundException("Question not found")

        quiz = await self.quiz_repo.get_by_id(question.quiz_id, school_id)
        if not quiz:
            raise NotFoundException("Quiz not found")

        await self._load_topic_for_write(quiz.topic_id, school_id, current_user)

        await self.question_repo.delete(question)
        # Recalculate total_marks
        questions = await self.question_repo.list_by_quiz(quiz.id)
        total = sum(q.marks for q in questions)
        await self.quiz_repo.update(quiz, {"total_marks": total})

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz Attempt (Student)
    # ─────────────────────────────────────────────────────────────────────────

    async def attempt_quiz(
        self,
        payload: AttemptCreate,
        current_user: CurrentUser,
        child_id: Optional[uuid.UUID] = None,
    ) -> AttemptResultResponse:
        """
        Submits a student quiz attempt and returns graded result.

        Decision #3: Multiple attempts allowed, no unique constraint.
        Academic year enforcement: only current year quizzes are attemptable.
        """
        school_id = self._require_school(current_user)
        if current_user.role not in (RoleEnum.STUDENT, RoleEnum.PARENT):
            raise ForbiddenException("Only students/parents can attempt quizzes")

        quiz = await self.quiz_repo.get_by_id(payload.quiz_id, school_id)
        if not quiz:
            raise NotFoundException("Quiz not found")

        # Enforce: quiz must not be manually locked
        if quiz.is_locked:
            raise ForbiddenException("This quiz is currently locked")

        # Resolve student_id (STUDENT = own, PARENT = child_id)
        student_id = await self._resolve_student_id_for_role(
            current_user, school_id, child_id
        )

        # Enforce: only current year attempts
        topic = await self.topic_repo.get_by_id(quiz.topic_id)
        if not topic:
            raise NotFoundException("Topic not found")
        chapter = await self.chapter_repo.get_by_id(topic.chapter_id, school_id)
        if not chapter:
            raise NotFoundException("Chapter not found")

        year = await self._load_academic_year(chapter.academic_year_id)
        if not self._is_current_year(year):
            raise ForbiddenException(
                "Quiz attempts are only allowed for the current academic year"
            )

        # Validate student enrollment
        await self._assert_student_enrollment(
            student_id,
            chapter.standard_id,
            chapter.section_id,
            chapter.academic_year_id,
            school_id,
        )

        # Grade the attempt
        questions = await self.question_repo.list_by_quiz(quiz.id)
        score = 0
        questions_with_results: list[dict[str, Any]] = []

        for q in questions:
            student_answer = payload.answers_json.get(str(q.id), "")
            is_correct = student_answer.strip().lower() == q.correct_answer.strip().lower()
            earned = q.marks if is_correct else 0
            score += earned
            questions_with_results.append({
                "question_id": str(q.id),
                "question_text": q.question_text,
                "student_answer": student_answer,
                "correct_answer": q.correct_answer,
                "is_correct": is_correct,
                "marks": q.marks,
                "earned": earned,
                "explanation": q.explanation,
            })

        total_marks = quiz.total_marks or sum(q.marks for q in questions)
        percentage = round((score / total_marks * 100), 2) if total_marks > 0 else 0.0

        attempt = await self.attempt_repo.create({
            "student_id": student_id,
            "quiz_id": quiz.id,
            "school_id": school_id,
            "academic_year_id": chapter.academic_year_id,
            "answers_json": payload.answers_json,
            "score": score,
            "total_marks": total_marks,
            "is_completed": True,
        })

        resp = AttemptResultResponse.model_validate(attempt)
        return resp.model_copy(update={
            "percentage": percentage,
            "questions_with_results": questions_with_results,
        })

    async def list_my_attempts(
        self,
        quiz_id: uuid.UUID,
        current_user: CurrentUser,
        child_id: Optional[uuid.UUID] = None,
    ) -> AttemptListResponse:
        school_id = self._require_school(current_user)
        if current_user.role not in (RoleEnum.STUDENT, RoleEnum.PARENT):
            raise ForbiddenException("Only students/parents can view own attempts")
        student_id = await self._resolve_student_id_for_role(
            current_user, school_id, child_id
        )

        attempts = await self.attempt_repo.list_by_student_quiz(student_id, quiz_id)
        best_score = await self.attempt_repo.get_best_score(student_id, quiz_id)
        latest_id = attempts[0].id if attempts else None

        return AttemptListResponse(
            items=[AttemptResponse.model_validate(a) for a in attempts],
            total=len(attempts),
            best_score=best_score,
            latest_attempt_id=latest_id,
        )

    async def list_quiz_attempts_teacher(
        self,
        quiz_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> AttemptListResponse:
        """Teacher/Admin: view all student attempts for a quiz."""
        school_id = self._require_school(current_user)
        quiz = await self.quiz_repo.get_by_id(quiz_id, school_id)
        if not quiz:
            raise NotFoundException("Quiz not found")

        if current_user.role == RoleEnum.TEACHER:
            topic = await self.topic_repo.get_by_id(quiz.topic_id)
            chapter = await self.chapter_repo.get_by_id(topic.chapter_id, school_id)
            await self._assert_teacher_access(
                current_user,
                standard_id=chapter.standard_id,
                section_id=chapter.section_id,
                subject_id=chapter.subject_id,
                academic_year_id=chapter.academic_year_id,
            )
        elif current_user.role not in (
            RoleEnum.PRINCIPAL,
            RoleEnum.SUPERADMIN,
            RoleEnum.TRUSTEE,
            RoleEnum.STAFF_ADMIN,
        ):
            raise ForbiddenException("Role not permitted to view quiz attempts")

        attempts = await self.attempt_repo.list_by_quiz(quiz_id, school_id)
        return AttemptListResponse(
            items=[AttemptResponse.model_validate(a) for a in attempts],
            total=len(attempts),
        )

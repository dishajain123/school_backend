import uuid
import json
from typing import Optional

from fastapi import UploadFile, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException
from app.integrations.minio_client import minio_client
from app.repositories.timetable import TimetableRepository
from app.repositories.settings import SettingsRepository
from app.schemas.timetable import TimetableUploadResponse, TimetableResponse
from app.services.academic_year import get_active_year
from app.services.student import StudentService
from app.utils.constants import MAX_FILE_SIZE_BYTES, ALLOWED_FILE_TYPES
from app.utils.enums import RoleEnum

TIMETABLE_BUCKET = "timetables"


class TimetableService:
    SECTIONS_REGISTRY_KEY = "class_sections_registry"

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TimetableRepository(db)
        self.settings_repo = SettingsRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    @staticmethod
    def _normalize_section(section: Optional[str]) -> Optional[str]:
        if section is None:
            return None
        normalized = section.strip()
        return normalized or None

    async def _register_section_for_school(
        self,
        *,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        section: Optional[str],
        updated_by: uuid.UUID,
    ) -> None:
        normalized = self._normalize_section(section)
        if normalized is None:
            return

        setting = await self.settings_repo.get_by_key(
            school_id,
            self.SECTIONS_REGISTRY_KEY,
        )
        registry: dict = {}
        if setting and setting.setting_value:
            try:
                parsed = json.loads(setting.setting_value)
                if isinstance(parsed, dict):
                    registry = parsed
            except (TypeError, ValueError):
                registry = {}

        standards_map = registry.setdefault("standards", {})
        if not isinstance(standards_map, dict):
            standards_map = {}
            registry["standards"] = standards_map

        std_key = str(standard_id)
        std_map = standards_map.setdefault(std_key, {})
        if not isinstance(std_map, dict):
            std_map = {}
            standards_map[std_key] = std_map

        year_key = str(academic_year_id)
        section_list = std_map.setdefault(year_key, [])
        if not isinstance(section_list, list):
            section_list = []

        existing = {str(s).strip().upper() for s in section_list if str(s).strip()}
        existing.add(normalized.upper())
        std_map[year_key] = sorted(existing, key=lambda x: x.lower())

        await self.settings_repo.upsert_settings(
            school_id=school_id,
            items=[
                {
                    "key": self.SECTIONS_REGISTRY_KEY,
                    "value": json.dumps(registry, separators=(",", ":")),
                }
            ],
            updated_by=updated_by,
        )

    async def _get_teacher_id(
        self,
        *,
        current_user: CurrentUser,
        school_id: uuid.UUID,
    ) -> uuid.UUID:
        from app.models.teacher import Teacher

        teacher_row = await self.db.execute(
            select(Teacher.id).where(
                and_(
                    Teacher.user_id == current_user.id,
                    Teacher.school_id == school_id,
                )
            )
        )
        teacher_id = teacher_row.scalar_one_or_none()
        if not teacher_id:
            raise ForbiddenException("Teacher profile not found")
        return teacher_id

    async def _get_teacher_sections(
        self,
        *,
        teacher_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> set[str]:
        from app.models.teacher_class_subject import TeacherClassSubject

        rows = await self.db.execute(
            select(TeacherClassSubject.section).where(
                and_(
                    TeacherClassSubject.teacher_id == teacher_id,
                    TeacherClassSubject.standard_id == standard_id,
                    TeacherClassSubject.academic_year_id == academic_year_id,
                )
            )
        )
        sections: set[str] = set()
        for raw in rows.scalars().all():
            normalized = self._normalize_section(raw)
            if normalized is not None:
                sections.add(normalized)
        return sections

    async def upload_timetable(
        self,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
        file: UploadFile,
        section: Optional[str] = None,
    ) -> TimetableUploadResponse:
        school_id = self._ensure_school(current_user)
        normalized_section = self._normalize_section(section)

        resolved_year_id = academic_year_id
        if not resolved_year_id:
            resolved_year_id = (await get_active_year(school_id, self.db)).id

        if current_user.role == RoleEnum.TEACHER:
            from app.models.teacher_class_subject import TeacherClassSubject

            teacher_id = await self._get_teacher_id(
                current_user=current_user,
                school_id=school_id,
            )

            assignment_q = select(TeacherClassSubject.id).where(
                and_(
                    TeacherClassSubject.teacher_id == teacher_id,
                    TeacherClassSubject.standard_id == standard_id,
                    TeacherClassSubject.academic_year_id == resolved_year_id,
                )
            )
            if normalized_section is not None:
                assignment_q = assignment_q.where(TeacherClassSubject.section == normalized_section)
            assignment_exists = (await self.db.execute(assignment_q)).scalar_one_or_none()
            if not assignment_exists:
                raise ForbiddenException(
                    "You can upload timetable only for your assigned class/section"
                )

        if not file or not file.filename:
            raise HTTPException(status_code=422, detail="File is required")

        content = await file.read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=422,
                detail=f"File too large. Max size is {MAX_FILE_SIZE_BYTES} bytes.",
            )
        if file.content_type and file.content_type not in ALLOWED_FILE_TYPES:
            raise HTTPException(status_code=422, detail="Unsupported file type")

        file_key = (
            f"{school_id}/{standard_id}/{resolved_year_id}/"
            f"{uuid.uuid4()}_{file.filename}"
        )
        minio_client.upload_file(
            bucket=TIMETABLE_BUCKET,
            key=file_key,
            file_bytes=content,
            content_type=file.content_type or "application/octet-stream",
        )

        existing = await self.repo.get_by_standard(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=resolved_year_id,
            section=normalized_section,
        )
        if existing:
            updated = await self.repo.update(
                existing,
                {"file_key": file_key, "uploaded_by": current_user.id},
            )
            await self._register_section_for_school(
                school_id=school_id,
                standard_id=standard_id,
                academic_year_id=resolved_year_id,
                section=normalized_section,
                updated_by=current_user.id,
            )
            await self.db.commit()
            await self.db.refresh(updated)
            data = TimetableUploadResponse.model_validate(updated)
            data.uploaded_by_name = (
                updated.uploader.full_name.strip()
                if updated.uploader and updated.uploader.full_name
                else None
            )
        else:
            created = await self.repo.create(
                {
                    "standard_id": standard_id,
                    "section": normalized_section,
                    "academic_year_id": resolved_year_id,
                    "file_key": file_key,
                    "uploaded_by": current_user.id,
                    "school_id": school_id,
                }
            )
            await self._register_section_for_school(
                school_id=school_id,
                standard_id=standard_id,
                academic_year_id=resolved_year_id,
                section=normalized_section,
                updated_by=current_user.id,
            )
            await self.db.commit()
            await self.db.refresh(created)
            data = TimetableUploadResponse.model_validate(created)
            data.uploaded_by_name = (
                created.uploader.full_name.strip()
                if created.uploader and created.uploader.full_name
                else None
            )

        data.file_url = minio_client.generate_presigned_url(
            TIMETABLE_BUCKET, file_key
        )
        return data

    async def delete_timetable(
        self,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
        section: Optional[str] = None,
    ) -> None:
        school_id = self._ensure_school(current_user)
        normalized_section = self._normalize_section(section)

        resolved_year_id = academic_year_id
        if not resolved_year_id:
            resolved_year_id = (await get_active_year(school_id, self.db)).id

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await self._get_teacher_id(
                current_user=current_user,
                school_id=school_id,
            )
            teacher_sections = await self._get_teacher_sections(
                teacher_id=teacher_id,
                standard_id=standard_id,
                academic_year_id=resolved_year_id,
            )
            if not teacher_sections:
                raise ForbiddenException(
                    "You can delete timetable only for your assigned class/section"
                )
            if normalized_section is not None and normalized_section not in teacher_sections:
                raise ForbiddenException(
                    "You can delete timetable only for your assigned class/section"
                )
            if normalized_section is None:
                class_wide = await self.repo.get_by_standard(
                    school_id=school_id,
                    standard_id=standard_id,
                    academic_year_id=resolved_year_id,
                    section=None,
                )
                if class_wide is None:
                    if len(teacher_sections) == 1:
                        normalized_section = next(iter(teacher_sections))
                    else:
                        raise ForbiddenException(
                            "Please select one of your assigned sections to delete timetable"
                        )

        timetable = await self.repo.get_by_standard(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=resolved_year_id,
            section=normalized_section,
        )
        if not timetable:
            raise NotFoundException("Timetable")

        file_key = timetable.file_key
        await self.repo.delete(timetable)
        await self.db.commit()

        try:
            minio_client.delete_file(TIMETABLE_BUCKET, file_key)
        except Exception:
            # Deletion from object storage is best-effort; DB state is source of truth.
            pass

    async def get_timetable(
        self,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
        section: Optional[str] = None,
    ) -> TimetableResponse:
        school_id = self._ensure_school(current_user)
        normalized_section = self._normalize_section(section)

        resolved_year_id = academic_year_id
        if not resolved_year_id:
            resolved_year_id = (await get_active_year(school_id, self.db)).id

        from app.models.student import Student

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await self._get_teacher_id(
                current_user=current_user,
                school_id=school_id,
            )
            teacher_sections = await self._get_teacher_sections(
                teacher_id=teacher_id,
                standard_id=standard_id,
                academic_year_id=resolved_year_id,
            )
            if not teacher_sections:
                raise ForbiddenException(
                    "You can only view timetable for your assigned class/section"
                )
            if normalized_section is not None and normalized_section not in teacher_sections:
                raise ForbiddenException(
                    "You can only view timetable for your assigned class/section"
                )
            if normalized_section is None:
                class_wide = await self.repo.get_by_standard(
                    school_id=school_id,
                    standard_id=standard_id,
                    academic_year_id=resolved_year_id,
                    section=None,
                )
                if class_wide is None:
                    if len(teacher_sections) == 1:
                        normalized_section = next(iter(teacher_sections))
                    else:
                        raise ForbiddenException(
                            "Please select one of your assigned sections to view timetable"
                        )

        elif current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.standard_id, Student.section).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            row = result.one_or_none()
            own_standard_id = row[0] if row else None
            own_section = self._normalize_section(row[1]) if row else None
            if not own_standard_id or own_standard_id != standard_id:
                raise ForbiddenException("You can only view your own class timetable")
            if own_section is not None:
                if normalized_section is not None and normalized_section != own_section:
                    raise ForbiddenException("You can only view your own class/section timetable")
                normalized_section = own_section

        elif current_user.role == RoleEnum.PARENT:
            result = await self.db.execute(
                select(Student.section).where(
                    and_(
                        Student.standard_id == standard_id,
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == school_id,
                        Student.academic_year_id == resolved_year_id,
                    )
                )
            )
            rows = result.scalars().all()
            if not rows:
                raise ForbiddenException(
                    "You can only view timetable for your linked child's class/section"
                )
            child_sections = {
                normalized
                for raw in rows
                if (normalized := self._normalize_section(raw)) is not None
            }
            if normalized_section is not None and normalized_section not in child_sections:
                raise ForbiddenException(
                    "You can only view timetable for your linked child's class/section"
                )
            if normalized_section is None:
                if len(child_sections) == 1:
                    normalized_section = next(iter(child_sections))
                elif len(child_sections) > 1:
                    raise ForbiddenException(
                        "Please select your child's section to view timetable"
                    )
        elif current_user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN):
            pass
        else:
            raise ForbiddenException(
                "Timetable is visible only to assigned teachers and students"
            )

        timetable = await self.repo.get_by_standard(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=resolved_year_id,
            section=normalized_section,
        )
        if not timetable:
            raise NotFoundException("Timetable")

        data = TimetableResponse.model_validate(timetable)
        data.uploaded_by_name = (
            timetable.uploader.full_name.strip()
            if timetable.uploader and timetable.uploader.full_name
            else None
        )
        data.file_url = minio_client.generate_presigned_url(
            TIMETABLE_BUCKET, timetable.file_key
        )
        return data

    async def list_sections(
        self,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
    ) -> list[str]:
        school_id = self._ensure_school(current_user)
        resolved_year_id = academic_year_id
        if not resolved_year_id:
            resolved_year_id = (await get_active_year(school_id, self.db)).id

        # Unify sections from timetable records + shared registry/student-backed
        # section source, so class/section options stay consistent app-wide.
        timetable_sections = await self.repo.list_sections_by_standard(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=resolved_year_id,
        )
        unified_sections = set(timetable_sections)
        student_sections = await StudentService(self.db).list_sections(
            school_id=school_id,
            current_user=current_user,
            standard_id=standard_id,
            academic_year_id=resolved_year_id,
        )
        unified_sections.update(
            section.strip()
            for section in student_sections
            if section and section.strip()
        )
        sections = sorted(unified_sections, key=lambda s: s.lower())

        if current_user.role == RoleEnum.TEACHER:
            teacher_id = await self._get_teacher_id(
                current_user=current_user,
                school_id=school_id,
            )
            teacher_sections = await self._get_teacher_sections(
                teacher_id=teacher_id,
                standard_id=standard_id,
                academic_year_id=resolved_year_id,
            )
            return [section for section in sections if section in teacher_sections]
        return sections

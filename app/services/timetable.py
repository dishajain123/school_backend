import uuid
from typing import Optional

from fastapi import UploadFile, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException
from app.integrations.minio_client import minio_client
from app.repositories.timetable import TimetableRepository
from app.schemas.timetable import TimetableUploadResponse, TimetableResponse
from app.services.academic_year import get_active_year
from app.utils.constants import MAX_FILE_SIZE_BYTES, ALLOWED_FILE_TYPES
from app.utils.enums import RoleEnum

TIMETABLE_BUCKET = "timetables"


class TimetableService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TimetableRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def upload_timetable(
        self,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
        file: UploadFile,
        section: Optional[str] = None,
    ) -> TimetableUploadResponse:
        school_id = self._ensure_school(current_user)

        resolved_year_id = academic_year_id
        if not resolved_year_id:
            resolved_year_id = (await get_active_year(school_id, self.db)).id

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
            section=section,
        )
        if existing:
            updated = await self.repo.update(
                existing,
                {"file_key": file_key, "uploaded_by": current_user.id},
            )
            await self.db.commit()
            await self.db.refresh(updated)
            data = TimetableUploadResponse.model_validate(updated)
        else:
            created = await self.repo.create(
                {
                    "standard_id": standard_id,
                    "section": section,
                    "academic_year_id": resolved_year_id,
                    "file_key": file_key,
                    "uploaded_by": current_user.id,
                    "school_id": school_id,
                }
            )
            await self.db.commit()
            await self.db.refresh(created)
            data = TimetableUploadResponse.model_validate(created)

        data.file_url = minio_client.generate_presigned_url(
            TIMETABLE_BUCKET, file_key
        )
        return data

    async def get_timetable(
        self,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
        section: Optional[str] = None,
    ) -> TimetableResponse:
        school_id = self._ensure_school(current_user)

        resolved_year_id = academic_year_id
        if not resolved_year_id:
            resolved_year_id = (await get_active_year(school_id, self.db)).id

        from app.models.student import Student

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.standard_id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_standard_id = result.scalar_one_or_none()
            if not own_standard_id or own_standard_id != standard_id:
                raise ForbiddenException("You can only view your own class timetable")

        elif current_user.role == RoleEnum.PARENT:
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

        timetable = await self.repo.get_by_standard(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=resolved_year_id,
            section=section,
        )
        if not timetable:
            raise NotFoundException("Timetable")

        data = TimetableResponse.model_validate(timetable)
        data.file_url = minio_client.generate_presigned_url(
            TIMETABLE_BUCKET, timetable.file_key
        )
        return data
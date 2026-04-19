import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException
from app.repositories.document import DocumentRepository
from app.schemas.document import (
    DocumentRequest,
    DocumentResponse,
    DocumentListResponse,
    DocumentDownloadResponse,
    DocumentVerifyRequest,
)
from app.services.academic_year import get_active_year
from app.integrations.minio_client import minio_client
from app.integrations import pdf_service
from app.utils.enums import RoleEnum, DocumentStatus, DocumentType

DOCUMENTS_BUCKET = "documents"


async def _generate_document(
    doc_id: uuid.UUID,
    school_id: uuid.UUID,
    document_type: DocumentType,
    student_id: uuid.UUID,
    academic_year_id: uuid.UUID,
) -> None:
    """
    Background task: opens its own DB session.
    Never reuses the request-scoped session.
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        repo = DocumentRepository(db)
        doc = await repo.get_by_id(doc_id, school_id)
        if not doc:
            return

        await repo.update(doc, {"status": DocumentStatus.PROCESSING})
        await db.commit()

        html = f"""
        <html><body>
        <h2>{document_type.replace('_', ' ').title()}</h2>
        <p>Student ID: {student_id}</p>
        <p>Academic Year ID: {academic_year_id}</p>
        <p>Generated at: {datetime.now(timezone.utc).isoformat()}</p>
        </body></html>
        """
        try:
            pdf_bytes = pdf_service.generate_pdf(html)
            file_key = f"{school_id}/{student_id}/{uuid.uuid4()}_{document_type}.pdf"
            minio_client.upload_file(
                bucket=DOCUMENTS_BUCKET,
                key=file_key,
                file_bytes=pdf_bytes,
                content_type="application/pdf",
            )
            # Re-fetch doc after commit to avoid stale state
            doc = await repo.get_by_id(doc_id, school_id)
            if doc:
                await repo.update(
                    doc,
                    {
                        "file_key": file_key,
                        "status": DocumentStatus.READY,
                        "generated_at": datetime.now(timezone.utc),
                    },
                )
                await db.commit()
        except Exception:
            doc = await repo.get_by_id(doc_id, school_id)
            if doc:
                await repo.update(doc, {"status": DocumentStatus.FAILED})
                await db.commit()


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DocumentRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    @staticmethod
    def _can_access_documents(current_user: CurrentUser) -> bool:
        return (
            "document:generate" in current_user.permissions
            or "document:manage" in current_user.permissions
        )

    @staticmethod
    def _can_manage_documents(current_user: CurrentUser) -> bool:
        return "document:manage" in current_user.permissions

    async def _assert_student_scope(
        self,
        current_user: CurrentUser,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> None:
        from app.models.student import Student

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
                raise ForbiddenException("You can only access your own documents")

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

    async def request_document(
        self,
        body: DocumentRequest,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> DocumentResponse:
        school_id = self._ensure_school(current_user)
        if not self._can_access_documents(current_user):
            raise ForbiddenException(
                "Permission 'document:generate' is required to access this resource"
            )
        if current_user.role == RoleEnum.TRUSTEE:
            raise ForbiddenException("Trustee can view documents but cannot request them")
        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        await self._assert_student_scope(current_user, school_id, body.student_id)

        doc = await self.repo.create(
            {
                "student_id": body.student_id,
                "document_type": body.document_type,
                "file_key": None,
                "status": DocumentStatus.PENDING,
                "generated_at": None,
                "academic_year_id": academic_year_id,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(doc)

        background_tasks.add_task(
            _generate_document,
            doc.id,
            school_id,
            body.document_type,
            body.student_id,
            academic_year_id,
        )

        return DocumentResponse.model_validate(doc)

    async def upload_document(
        self,
        student_id: uuid.UUID,
        document_type: DocumentType,
        file: UploadFile,
        current_user: CurrentUser,
    ) -> DocumentResponse:
        school_id = self._ensure_school(current_user)
        if not self._can_access_documents(current_user):
            raise ForbiddenException(
                "Permission 'document:generate' is required to access this resource"
            )
        if current_user.role == RoleEnum.TRUSTEE:
            raise ForbiddenException("Trustee can view documents but cannot upload them")
        if current_user.role == RoleEnum.TEACHER and document_type != DocumentType.ID_CARD:
            raise ForbiddenException("Teacher can upload only ID card documents")

        await self._assert_student_scope(current_user, school_id, student_id)

        content = await file.read()
        if not content:
            raise ValidationException("Uploaded file is empty")

        active_year = await get_active_year(school_id, self.db)
        safe_name = file.filename or f"{document_type.value.lower()}.bin"
        file_key = f"{school_id}/{student_id}/{uuid.uuid4()}_{safe_name}"
        minio_client.upload_file(
            bucket=DOCUMENTS_BUCKET,
            key=file_key,
            file_bytes=content,
            content_type=file.content_type or "application/octet-stream",
        )

        auto_ready = current_user.role in (
            RoleEnum.PRINCIPAL,
            RoleEnum.SUPERADMIN,
            RoleEnum.TEACHER,
        )
        status = DocumentStatus.READY if auto_ready else DocumentStatus.PROCESSING

        doc = await self.repo.create(
            {
                "student_id": student_id,
                "document_type": document_type,
                "file_key": file_key,
                "status": status,
                "generated_at": datetime.now(timezone.utc) if auto_ready else None,
                "academic_year_id": active_year.id,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(doc)
        return DocumentResponse.model_validate(doc)

    async def list_documents(
        self,
        student_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> DocumentListResponse:
        school_id = self._ensure_school(current_user)
        if not self._can_access_documents(current_user):
            raise ForbiddenException(
                "Permission 'document:generate' is required to access this resource"
            )
        await self._assert_student_scope(current_user, school_id, student_id)

        docs = await self.repo.list_for_student(student_id, school_id)
        return DocumentListResponse(
            items=[DocumentResponse.model_validate(d) for d in docs],
            total=len(docs),
        )

    async def download_document(
        self,
        document_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> DocumentDownloadResponse:
        school_id = self._ensure_school(current_user)
        if not self._can_access_documents(current_user):
            raise ForbiddenException(
                "Permission 'document:generate' is required to access this resource"
            )
        doc = await self.repo.get_by_id(document_id, school_id)
        if not doc:
            raise NotFoundException("Document")

        await self._assert_student_scope(current_user, school_id, doc.student_id)

        if doc.status != DocumentStatus.READY or not doc.file_key:
            return DocumentDownloadResponse(status=doc.status, url=None)

        url = minio_client.generate_presigned_url(DOCUMENTS_BUCKET, doc.file_key)
        return DocumentDownloadResponse(status=doc.status, url=url)

    async def verify_document(
        self,
        document_id: uuid.UUID,
        body: DocumentVerifyRequest,
        current_user: CurrentUser,
    ) -> DocumentResponse:
        school_id = self._ensure_school(current_user)
        if not self._can_manage_documents(current_user):
            raise ForbiddenException(
                "Permission 'document:manage' is required to access this resource"
            )
        if current_user.role not in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN):
            raise ForbiddenException("Only principal can verify student documents")

        doc = await self.repo.get_by_id(document_id, school_id)
        if not doc:
            raise NotFoundException("Document")
        if not doc.file_key:
            raise ValidationException("Uploaded file is missing for this document")

        status = DocumentStatus.READY if body.approve else DocumentStatus.FAILED
        await self.repo.update(
            doc,
            {
                "status": status,
                "generated_at": datetime.now(timezone.utc)
                if body.approve
                else None,
            },
        )
        await self.db.commit()
        await self.db.refresh(doc)
        return DocumentResponse.model_validate(doc)

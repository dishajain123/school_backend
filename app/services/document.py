import uuid
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException
from app.repositories.document import DocumentRepository
from app.repositories.notification import NotificationRepository
from app.repositories.settings import SettingsRepository
from app.schemas.document import (
    DocumentRequest,
    DocumentResponse,
    DocumentListResponse,
    DocumentDownloadResponse,
    DocumentVerifyRequest,
    DocumentRequirementsUpsertRequest,
    DocumentRequirementsResponse,
    DocumentRequirementResponse,
    DocumentRequirementStatusResponse,
)
from app.services.academic_year import get_active_year
from app.services.audit_log import AuditLogService
from app.integrations.minio_client import minio_client
from app.integrations import pdf_service
from app.utils.constants import MAX_FILE_SIZE_BYTES
from app.utils.enums import (
    RoleEnum,
    DocumentStatus,
    DocumentType,
    NotificationType,
    NotificationPriority,
    AuditAction,
)

DOCUMENTS_BUCKET = "documents"
DOCUMENT_REQUIREMENTS_KEY = "document_requirements_v1"
DOCUMENT_REVIEW_META_KEY = "document_review_meta_v1"


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
        document_type_value = (
            document_type.value
            if isinstance(document_type, DocumentType)
            else str(document_type)
        )

        await repo.update(doc, {"status": DocumentStatus.PROCESSING})
        await db.commit()

        html = f"""
        <html><body>
        <h2>{document_type_value.replace('_', ' ').title()}</h2>
        <p>Student ID: {student_id}</p>
        <p>Academic Year ID: {academic_year_id}</p>
        <p>Generated at: {datetime.now(timezone.utc).isoformat()}</p>
        </body></html>
        """
        try:
            pdf_bytes = pdf_service.generate_pdf(html)
            file_key = (
                f"{school_id}/{student_id}/"
                f"{uuid.uuid4()}_{document_type_value}.pdf"
            )
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
                await repo.update(
                    doc,
                    {
                        "status": DocumentStatus.FAILED,
                        "generated_at": None,
                    },
                )
                await db.commit()


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DocumentRepository(db)
        self.settings_repo = SettingsRepository(db)
        self.notification_repo = NotificationRepository(db)
        self.audit_service = AuditLogService(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    @staticmethod
    def _can_access_documents(current_user: CurrentUser) -> bool:
        if current_user.role in (
            RoleEnum.PRINCIPAL,
            RoleEnum.SUPERADMIN,
            RoleEnum.TEACHER,
            RoleEnum.STUDENT,
            RoleEnum.PARENT,
        ):
            return True
        return (
            "document:generate" in current_user.permissions
            or "document:manage" in current_user.permissions
        )

    @staticmethod
    def _can_manage_documents(current_user: CurrentUser) -> bool:
        return "document:manage" in current_user.permissions

    async def _load_json_setting(self, school_id: uuid.UUID, key: str) -> dict:
        setting = await self.settings_repo.get_by_key(school_id, key)
        if not setting or not setting.setting_value:
            return {}
        try:
            parsed = json.loads(setting.setting_value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    async def _upsert_json_setting(
        self,
        *,
        school_id: uuid.UUID,
        key: str,
        payload: dict,
        updated_by: Optional[uuid.UUID],
    ) -> None:
        await self.settings_repo.upsert_settings(
            school_id=school_id,
            items=[
                {
                    "key": key,
                    "value": json.dumps(payload, separators=(",", ":")),
                }
            ],
            updated_by=updated_by,
        )

    async def _get_requirement_items(
        self,
        school_id: uuid.UUID,
        *,
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        include_global: bool = True,
    ) -> list[dict]:
        raw = await self._load_json_setting(school_id, DOCUMENT_REQUIREMENTS_KEY)
        items = raw.get("items", [])
        if not isinstance(items, list):
            return []

        cleaned: list[dict] = []
        for row in items:
            if not isinstance(row, dict):
                continue
            value = str(row.get("document_type") or "").strip().upper()
            if value not in DocumentType.__members__:
                continue
            row_year = self._parse_optional_uuid(row.get("academic_year_id"))
            row_standard = self._parse_optional_uuid(row.get("standard_id"))
            if academic_year_id is not None:
                if row_year is None and not include_global:
                    continue
                if row_year is not None and row_year != academic_year_id:
                    continue
            if standard_id is not None:
                if row_standard is None and not include_global:
                    continue
                if row_standard is not None and row_standard != standard_id:
                    continue
            note_raw = row.get("note")
            note = str(note_raw).strip() if isinstance(note_raw, str) else None
            cleaned.append(
                {
                    "document_type": value,
                    "is_mandatory": bool(row.get("is_mandatory", True)),
                    "note": note or None,
                    "academic_year_id": str(row_year) if row_year else None,
                    "standard_id": str(row_standard) if row_standard else None,
                }
            )
        # Deduplicate while preserving distinct OTHER names in same scope.
        dedup: dict[str, dict] = {}
        for item in cleaned:
            key = self._requirement_key(item)
            dedup[key] = item
        return list(dedup.values())

    async def _required_doc_type_set(self, school_id: uuid.UUID) -> set[DocumentType]:
        items = await self._get_requirement_items(school_id)
        return {
            DocumentType[row["document_type"]]
            for row in items
            if row.get("is_mandatory", True)
        }

    async def _get_review_meta_map(self, school_id: uuid.UUID) -> dict[str, dict]:
        raw = await self._load_json_setting(school_id, DOCUMENT_REVIEW_META_KEY)
        docs = raw.get("documents", {})
        return docs if isinstance(docs, dict) else {}

    async def _save_review_meta_for_document(
        self,
        *,
        school_id: uuid.UUID,
        document_id: uuid.UUID,
        review_note: Optional[str],
        reviewed_by: Optional[uuid.UUID],
        reviewed_at: Optional[datetime],
        updated_by: Optional[uuid.UUID],
    ) -> None:
        raw = await self._load_json_setting(school_id, DOCUMENT_REVIEW_META_KEY)
        docs = raw.setdefault("documents", {})
        if not isinstance(docs, dict):
            docs = {}
            raw["documents"] = docs

        doc_key = str(document_id)
        if review_note or reviewed_by or reviewed_at:
            docs[doc_key] = {
                "review_note": (review_note or "").strip() or None,
                "reviewed_by": str(reviewed_by) if reviewed_by else None,
                "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
            }
        else:
            docs.pop(doc_key, None)

        await self._upsert_json_setting(
            school_id=school_id,
            key=DOCUMENT_REVIEW_META_KEY,
            payload=raw,
            updated_by=updated_by,
        )

    async def _save_request_note_for_document(
        self,
        *,
        school_id: uuid.UUID,
        document_id: uuid.UUID,
        note: Optional[str],
        updated_by: Optional[uuid.UUID],
    ) -> None:
        note_clean = " ".join((note or "").strip().split()) or None
        raw = await self._load_json_setting(school_id, DOCUMENT_REVIEW_META_KEY)
        docs = raw.setdefault("documents", {})
        if not isinstance(docs, dict):
            docs = {}
            raw["documents"] = docs

        doc_key = str(document_id)
        existing = docs.get(doc_key)
        if not isinstance(existing, dict):
            existing = {}

        if note_clean:
            existing["request_note"] = note_clean
            docs[doc_key] = existing
        else:
            existing.pop("request_note", None)
            if existing:
                docs[doc_key] = existing
            else:
                docs.pop(doc_key, None)

        await self._upsert_json_setting(
            school_id=school_id,
            key=DOCUMENT_REVIEW_META_KEY,
            payload=raw,
            updated_by=updated_by,
        )

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

    async def _get_student_user_targets(
        self,
        *,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> tuple[Optional[uuid.UUID], Optional[uuid.UUID], Optional[str]]:
        from app.models.student import Student
        from app.models.parent import Parent
        from app.models.user import User

        row = await self.db.execute(
            select(
                Student.user_id,
                Parent.user_id,
                User.email,
            )
            .select_from(Student)
            .join(Parent, Parent.id == Student.parent_id, isouter=True)
            .join(User, User.id == Student.user_id, isouter=True)
            .where(
                and_(
                    Student.id == student_id,
                    Student.school_id == school_id,
                )
            )
        )
        result = row.first()
        if not result:
            return None, None, None
        student_user_id, parent_user_id, email = result
        display_name = email
        return student_user_id, parent_user_id, display_name

    async def _notify_document_status(
        self,
        *,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
        title: str,
        body: str,
        reference_id: Optional[uuid.UUID],
    ) -> None:
        student_user_id, parent_user_id, _ = await self._get_student_user_targets(
            school_id=school_id,
            student_id=student_id,
        )
        target_ids = [uid for uid in (student_user_id, parent_user_id) if uid]
        for user_id in target_ids:
            await self.notification_repo.create(
                {
                    "user_id": user_id,
                    "title": title,
                    "body": body,
                    "type": NotificationType.SYSTEM,
                    "priority": NotificationPriority.MEDIUM,
                    "reference_id": reference_id,
                }
            )

    @staticmethod
    def _parse_optional_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
        if not value:
            return None
        try:
            return uuid.UUID(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_other_note(note: Optional[str]) -> Optional[str]:
        if not isinstance(note, str):
            return None
        cleaned = " ".join(note.strip().split())
        return cleaned.lower() if cleaned else None

    @classmethod
    def _requirement_key(cls, item: dict) -> str:
        doc_type = str(item.get("document_type") or "").strip().upper()
        year = item.get("academic_year_id") or "*"
        standard = item.get("standard_id") or "*"
        if doc_type == DocumentType.OTHER.value:
            normalized_note = cls._normalize_other_note(item.get("note")) or "*"
            return f"{doc_type}|{normalized_note}|{year}|{standard}"
        return f"{doc_type}|{year}|{standard}"

    def _serialize_document_response(
        self,
        doc,
        review_meta_map: Optional[dict[str, dict]] = None,
        student_meta: Optional[dict[uuid.UUID, dict]] = None,
    ) -> DocumentResponse:
        payload = DocumentResponse.model_validate(doc).model_dump()
        meta = (review_meta_map or {}).get(str(doc.id), {})
        payload["review_note"] = meta.get("review_note")
        payload["reviewed_by"] = self._parse_optional_uuid(meta.get("reviewed_by"))
        payload["reviewed_at"] = self._parse_optional_datetime(meta.get("reviewed_at"))
        s_meta = (student_meta or {}).get(doc.student_id, {})
        payload["student_name"] = s_meta.get("student_name")
        payload["student_admission_number"] = s_meta.get("admission_number")
        payload["parent_name"] = s_meta.get("parent_name")
        return DocumentResponse(**payload)

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
        # Student/parent may request any document type for admin to issue or upload
        # (ID card, report card, etc.). Upload restrictions use required-doc rules only
        # in upload_document(), not here.

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
        if body.document_type == DocumentType.OTHER and (body.note or "").strip():
            await self._save_request_note_for_document(
                school_id=school_id,
                document_id=doc.id,
                note=body.note,
                updated_by=current_user.id,
            )
        await self.db.commit()
        await self.db.refresh(doc)

        return self._serialize_document_response(doc)

    async def upload_document(
        self,
        student_id: uuid.UUID,
        document_type: DocumentType,
        file: UploadFile,
        note: Optional[str],
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
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise ValidationException(
                f"Uploaded file exceeds maximum size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB"
            )
        if current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT):
            required_types = await self._required_doc_type_set(school_id)
            if required_types and document_type not in required_types:
                raise ForbiddenException(
                    "This document type is not requested by school for upload"
                )
            content_type = (file.content_type or "").strip().lower()
            filename = (file.filename or "").strip().lower()
            if content_type != "application/pdf" and not filename.endswith(".pdf"):
                raise ValidationException(
                    "Students/parents can upload documents only in PDF format"
                )

        active_year = await get_active_year(school_id, self.db)
        safe_name = file.filename or f"{document_type.value.lower()}.bin"
        file_key = f"{school_id}/{student_id}/{uuid.uuid4()}_{safe_name}"
        minio_client.upload_file(
            bucket=DOCUMENTS_BUCKET,
            key=file_key,
            file_bytes=content,
            content_type=file.content_type or "application/octet-stream",
        )

        # Upload and verification are separate steps.
        # Admin verifies explicitly from console; students/parents see updated status in app.
        status = DocumentStatus.PROCESSING

        existing_request = await self.repo.get_latest_pending_request(
            student_id=student_id,
            school_id=school_id,
            academic_year_id=active_year.id,
            document_type=document_type,
        )
        if existing_request is not None:
            doc = await self.repo.update(
                existing_request,
                {
                    "file_key": file_key,
                    "status": status,
                    "generated_at": None,
                },
            )
        else:
            doc = await self.repo.create(
                {
                    "student_id": student_id,
                    "document_type": document_type,
                    "file_key": file_key,
                    "status": status,
                    "generated_at": None,
                    "academic_year_id": active_year.id,
                    "school_id": school_id,
                }
            )
        if document_type == DocumentType.OTHER and (note or "").strip():
            await self._save_request_note_for_document(
                school_id=school_id,
                document_id=doc.id,
                note=note,
                updated_by=current_user.id,
            )
        if current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT):
            await self._notify_document_status(
                school_id=school_id,
                student_id=student_id,
                title="Document Uploaded",
                body=f"{document_type.value.replace('_', ' ').title()} uploaded and sent for verification.",
                reference_id=doc.id,
            )
        await self.db.commit()
        await self.db.refresh(doc)
        return self._serialize_document_response(doc)

    async def list_documents(
        self,
        student_id: Optional[uuid.UUID],
        current_user: CurrentUser,
        *,
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
    ) -> DocumentListResponse:
        school_id = self._ensure_school(current_user)
        if not self._can_access_documents(current_user):
            raise ForbiddenException(
                "Permission 'document:generate' is required to access this resource"
            )
        is_admin = current_user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)
        if student_id is None and not is_admin:
            raise ValidationException("student_id is required")

        if student_id is not None:
            await self._assert_student_scope(current_user, school_id, student_id)
            docs = await self.repo.list_for_student(student_id, school_id)
        else:
            normalized_section = (section or "").strip() or None
            docs = await self.repo.list_for_school(
                school_id,
                academic_year_id=academic_year_id,
                standard_id=standard_id,
                section=normalized_section,
            )

        review_meta_map = await self._get_review_meta_map(school_id)
        required = (
            await self.list_required_documents_for_student(
                student_id=student_id,
                current_user=current_user,
            )
            if student_id is not None
            else []
        )
        student_meta: dict[uuid.UUID, dict] = {}
        if student_id is None and docs:
            from app.models.student import Student
            from app.models.parent import Parent
            from app.models.user import User

            student_ids = list({d.student_id for d in docs})
            rows = await self.db.execute(
                select(
                    Student.id,
                    Student.admission_number,
                    User.email,
                    Parent.user_id,
                )
                .select_from(Student)
                .join(User, User.id == Student.user_id, isouter=True)
                .join(Parent, Parent.id == Student.parent_id, isouter=True)
                .where(
                    and_(
                        Student.id.in_(student_ids),
                        Student.school_id == school_id,
                    )
                )
            )
            parent_user_ids: list[uuid.UUID] = []
            parent_user_by_student: dict[uuid.UUID, uuid.UUID] = {}
            for sid, admission, student_email, parent_user_id in rows.all():
                student_meta[sid] = {
                    "admission_number": admission,
                    "student_name": student_email,
                    "parent_name": None,
                }
                if parent_user_id:
                    parent_user_ids.append(parent_user_id)
                    parent_user_by_student[sid] = parent_user_id

            parent_name_map: dict[uuid.UUID, str] = {}
            if parent_user_ids:
                parent_rows = await self.db.execute(
                    select(User.id, User.email).where(User.id.in_(parent_user_ids))
                )
                for uid, email in parent_rows.all():
                    if uid and email:
                        parent_name_map[uid] = email

            for sid, p_uid in parent_user_by_student.items():
                if sid in student_meta:
                    student_meta[sid]["parent_name"] = parent_name_map.get(p_uid)

        return DocumentListResponse(
            items=[
                self._serialize_document_response(d, review_meta_map, student_meta)
                for d in docs
            ],
            total=len(docs),
            required_documents=required,
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

        # Presign whenever a file exists so admins can review PROCESSING uploads
        # and users can open uploads pending verification or rejected copies.
        if not doc.file_key:
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
        can_verify = current_user.role in (
            RoleEnum.PRINCIPAL,
            RoleEnum.SUPERADMIN,
            RoleEnum.STAFF_ADMIN,
        )
        if not can_verify:
            raise ForbiddenException(
                "Only admin roles can verify or reject student documents"
            )

        doc = await self.repo.get_by_id(document_id, school_id)
        if not doc:
            raise NotFoundException("Document")
        if body.approve and not doc.file_key:
            raise ValidationException(
                "Cannot verify document before upload completes"
            )

        old_status = doc.status
        status = DocumentStatus.READY if body.approve else DocumentStatus.FAILED
        reviewed_at = datetime.now(timezone.utc)
        reason = (body.reason or "").strip() or None
        await self.repo.update(
            doc,
            {
                "status": status,
                "generated_at": reviewed_at
                if body.approve
                else None,
            },
        )
        await self._save_review_meta_for_document(
            school_id=school_id,
            document_id=doc.id,
            review_note=reason,
            reviewed_by=current_user.id,
            reviewed_at=reviewed_at,
            updated_by=current_user.id,
        )
        title = "Document Approved" if body.approve else "Document Rejected"
        base_label = doc.document_type.value.replace("_", " ").title()
        if body.approve:
            notify_body = f"{base_label} has been approved."
        else:
            suffix = f" Reason: {reason}" if reason else ""
            notify_body = (
                f"{base_label} was rejected. Please re-upload the document.{suffix}"
            )
        await self._notify_document_status(
            school_id=school_id,
            student_id=doc.student_id,
            title=title,
            body=notify_body,
            reference_id=doc.id,
        )
        await self.audit_service.log(
            action=AuditAction.DOCUMENT_APPROVED if body.approve else AuditAction.DOCUMENT_REJECTED,
            actor_id=current_user.id,
            target_user_id=None,
            entity_type="Document",
            entity_id=str(doc.id),
            description=title,
            before_state={"status": old_status.value},
            after_state={
                "status": status.value,
                "review_note": reason,
                "student_id": str(doc.student_id),
                "document_type": doc.document_type.value,
            },
            school_id=school_id,
        )
        await self.db.commit()
        await self.db.refresh(doc)
        review_meta_map = await self._get_review_meta_map(school_id)
        return self._serialize_document_response(doc, review_meta_map)

    async def upsert_required_documents(
        self,
        body: DocumentRequirementsUpsertRequest,
        current_user: CurrentUser,
    ) -> DocumentRequirementsResponse:
        school_id = self._ensure_school(current_user)
        if current_user.role not in (
            RoleEnum.PRINCIPAL,
            RoleEnum.SUPERADMIN,
            RoleEnum.STAFF_ADMIN,
        ):
            raise ForbiddenException("Only admin roles can manage required documents")
        if not self._can_manage_documents(current_user):
            raise ForbiddenException(
                "Permission 'document:manage' is required to access this resource"
            )

        dedup: dict[str, dict] = {}
        for item in body.items:
            note = " ".join((item.note or "").strip().split()) or None
            if item.document_type == DocumentType.OTHER and not note:
                raise ValidationException(
                    "Custom name is required for OTHER document type"
                )
            year_key = str(item.academic_year_id) if item.academic_year_id else None
            standard_key = str(item.standard_id) if item.standard_id else None
            row = {
                "document_type": item.document_type.value.upper(),
                "is_mandatory": bool(item.is_mandatory),
                "note": note,
                "academic_year_id": year_key,
                "standard_id": standard_key,
            }
            dedup[self._requirement_key(row)] = row

        payload = {
            "items": sorted(
                dedup.values(),
                key=lambda row: (
                    row.get("academic_year_id") or "",
                    row.get("standard_id") or "",
                    row["document_type"],
                ),
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._upsert_json_setting(
            school_id=school_id,
            key=DOCUMENT_REQUIREMENTS_KEY,
            payload=payload,
            updated_by=current_user.id,
        )
        await self.db.commit()
        return DocumentRequirementsResponse(
            items=[
                DocumentRequirementResponse(
                    document_type=DocumentType[row["document_type"]],
                    is_mandatory=bool(row.get("is_mandatory", True)),
                    note=row.get("note"),
                    academic_year_id=self._parse_optional_uuid(row.get("academic_year_id")),
                    standard_id=self._parse_optional_uuid(row.get("standard_id")),
                )
                for row in payload["items"]
            ]
        )

    async def list_required_documents(
        self,
        current_user: CurrentUser,
        *,
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
    ) -> DocumentRequirementsResponse:
        school_id = self._ensure_school(current_user)
        if not self._can_access_documents(current_user):
            raise ForbiddenException(
                "Permission 'document:generate' is required to access this resource"
            )
        items = await self._get_requirement_items(
            school_id,
            academic_year_id=academic_year_id,
            standard_id=standard_id,
            include_global=True,
        )
        return DocumentRequirementsResponse(
            items=[
                DocumentRequirementResponse(
                    document_type=DocumentType[row["document_type"]],
                    is_mandatory=bool(row.get("is_mandatory", True)),
                    note=row.get("note"),
                    academic_year_id=self._parse_optional_uuid(row.get("academic_year_id")),
                    standard_id=self._parse_optional_uuid(row.get("standard_id")),
                )
                for row in items
            ]
        )

    async def list_required_documents_for_student(
        self,
        *,
        student_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> list[DocumentRequirementStatusResponse]:
        school_id = self._ensure_school(current_user)
        await self._assert_student_scope(current_user, school_id, student_id)

        from app.models.student import Student
        srow = await self.db.execute(
            select(Student.standard_id, Student.academic_year_id).where(
                and_(Student.id == student_id, Student.school_id == school_id)
            )
        )
        student_scope = srow.first()
        if not student_scope:
            raise NotFoundException("Student")
        student_standard_id, student_year_id = student_scope

        required_items = await self._get_requirement_items(
            school_id,
            academic_year_id=student_year_id,
            standard_id=student_standard_id,
            include_global=True,
        )
        if not required_items:
            return []

        docs = await self.repo.list_for_student(student_id, school_id)
        latest_by_type: dict[DocumentType, object] = {}
        for doc in docs:
            if doc.document_type not in latest_by_type:
                latest_by_type[doc.document_type] = doc

        review_meta_map = await self._get_review_meta_map(school_id)
        latest_other_by_key: dict[str, object] = {}
        for doc in docs:
            if doc.document_type != DocumentType.OTHER:
                continue
            meta = review_meta_map.get(str(doc.id), {})
            request_note = meta.get("request_note") if isinstance(meta, dict) else None
            key = self._requirement_key(
                {
                    "document_type": DocumentType.OTHER.value,
                    "note": request_note,
                    "academic_year_id": str(student_year_id),
                    "standard_id": str(student_standard_id) if student_standard_id else None,
                }
            )
            if key not in latest_other_by_key:
                latest_other_by_key[key] = doc
        statuses: list[DocumentRequirementStatusResponse] = []
        for item in required_items:
            doc_type = DocumentType[item["document_type"]]
            latest_doc = latest_by_type.get(doc_type)
            if doc_type == DocumentType.OTHER:
                latest_doc = latest_other_by_key.get(self._requirement_key(item))
            meta = review_meta_map.get(str(latest_doc.id), {}) if latest_doc else {}
            latest_status = latest_doc.status if latest_doc else None
            needs_reupload = latest_status == DocumentStatus.FAILED
            is_completed = latest_status == DocumentStatus.READY
            statuses.append(
                DocumentRequirementStatusResponse(
                    document_type=doc_type,
                    is_mandatory=bool(item.get("is_mandatory", True)),
                    note=item.get("note"),
                    latest_document_id=latest_doc.id if latest_doc else None,
                    latest_status=latest_status,
                    uploaded_at=latest_doc.requested_at if latest_doc else None,
                    review_note=meta.get("review_note"),
                    reviewed_by=self._parse_optional_uuid(meta.get("reviewed_by")),
                    reviewed_at=self._parse_optional_datetime(meta.get("reviewed_at")),
                    needs_reupload=needs_reupload,
                    is_completed=is_completed,
                    academic_year_id=self._parse_optional_uuid(item.get("academic_year_id")),
                    standard_id=self._parse_optional_uuid(item.get("standard_id")),
                )
            )
        return statuses

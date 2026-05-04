import uuid
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import select, and_, inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException
from app.integrations.minio_client import minio_client
from app.repositories.complaint import ComplaintRepository
from app.repositories.notification import NotificationRepository
from app.schemas.complaint import (
    ComplaintCreate,
    ComplaintStatusUpdate,
    ComplaintResponse,
    ComplaintListResponse,
    FeedbackCreate,
    FeedbackResponse,
)
from app.utils.enums import (
    RoleEnum,
    NotificationType,
    NotificationPriority,
    ComplaintStatus,
    ComplaintCategory,
)

COMPLAINTS_BUCKET = "documents"


async def _notify_complaint_resolved(
    user_id: uuid.UUID,
    complaint_id: uuid.UUID,
) -> None:
    """Opens its own DB session — never reuses the request session."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        repo = NotificationRepository(db)
        await repo.create(
            {
                "user_id": user_id,
                "title": "Complaint Update",
                "body": "Your complaint status has been updated.",
                "type": NotificationType.COMPLAINT,
                "priority": NotificationPriority.MEDIUM,
                "reference_id": complaint_id,
            }
        )
        await db.commit()


class ComplaintService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ComplaintRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    @staticmethod
    def _user_display_name(user) -> str:
        if user is None:
            return "Unknown"
        email = (user.email or "").strip()
        if email:
            local_part = email.split("@", 1)[0]
            parts = [p for p in local_part.replace("_", ".").split(".") if p]
            if parts:
                return " ".join(p[:1].upper() + p[1:] for p in parts)
            return local_part
        phone = (user.phone or "").strip()
        if phone:
            return phone
        return "Unknown"

    @staticmethod
    def _can_manage_status(current_user: CurrentUser) -> bool:
        return (
            "complaint:read" in current_user.permissions
            and current_user.role
            in (RoleEnum.PRINCIPAL, RoleEnum.TRUSTEE, RoleEnum.STAFF_ADMIN)
        )

    def _build_response(
        self,
        complaint,
        *,
        current_user: Optional[CurrentUser] = None,
    ) -> ComplaintResponse:
        data = ComplaintResponse.model_validate(complaint)
        submitter = None
        try:
            state = inspect(complaint)
            if "submitter" not in state.unloaded:
                submitter = complaint.submitter
        except Exception:
            submitter = None

        if submitter is not None:
            data.submitted_by_name = self._user_display_name(submitter)
            data.submitted_by_role = submitter.role
        if complaint.attachment_key:
            try:
                data.attachment_url = minio_client.generate_presigned_url(
                    COMPLAINTS_BUCKET, complaint.attachment_key
                )
            except Exception:
                # Do not fail complaint APIs if object-storage URL generation fails.
                data.attachment_url = None
        is_owner_view = (
            current_user is not None
            and complaint.submitted_by is not None
            and complaint.submitted_by == current_user.id
        )
        if complaint.is_anonymous and not is_owner_view:
            data.submitted_by = None
            data.submitted_by_name = None
            data.submitted_by_role = None
        return data

    async def create_complaint(
        self,
        body: ComplaintCreate,
        current_user: CurrentUser,
    ) -> ComplaintResponse:
        if current_user.role == RoleEnum.PRINCIPAL:
            raise ForbiddenException("Principal cannot raise complaints")
        school_id = self._ensure_school(current_user)

        complaint = await self.repo.create_complaint(
            {
                "school_id": school_id,
                # Always persist owner so role-based own-complaint visibility works.
                "submitted_by": current_user.id,
                "category": body.category,
                "description": body.description,
                "attachment_key": body.attachment_key,
                "status": ComplaintStatus.OPEN,
                "resolved_by": None,
                "resolution_note": None,
                "is_anonymous": body.is_anonymous,
            }
        )
        await self.db.refresh(complaint)

        # Reload with eager-loaded relationships to avoid async lazy-load issues.
        complaint_with_relations = await self.repo.get_complaint_by_id(
            complaint.id, school_id
        )
        return self._build_response(
            complaint_with_relations or complaint,
            current_user=current_user,
        )

    async def list_complaints(
        self,
        current_user: CurrentUser,
        status: Optional[ComplaintStatus],
        category: Optional[ComplaintCategory],
        submitted_by_role: Optional[RoleEnum],
    ) -> ComplaintListResponse:
        school_id = self._ensure_school(current_user)

        submitted_by: Optional[uuid.UUID] = None
        if current_user.role in (RoleEnum.TEACHER, RoleEnum.STUDENT, RoleEnum.PARENT):
            submitted_by = current_user.id

        role_filter = submitted_by_role
        if role_filter in (RoleEnum.PRINCIPAL, RoleEnum.TRUSTEE, RoleEnum.STAFF_ADMIN):
            role_filter = None

        complaints = await self.repo.list_complaints(
            school_id=school_id,
            status=status,
            category=category,
            submitted_by_role=role_filter,
            submitted_by=submitted_by,
        )
        return ComplaintListResponse(
            items=[
                self._build_response(c, current_user=current_user)
                for c in complaints
            ],
            total=len(complaints),
        )

    async def update_status(
        self,
        complaint_id: uuid.UUID,
        body: ComplaintStatusUpdate,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> ComplaintResponse:
        school_id = self._ensure_school(current_user)
        if not self._can_manage_status(current_user):
            raise ForbiddenException(
                "Only principal, trustee, or staff admin can update complaint status"
            )
        complaint = await self.repo.get_complaint_by_id(complaint_id, school_id)
        if not complaint:
            raise NotFoundException("Complaint")

        transitions = {
            ComplaintStatus.OPEN: ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.IN_PROGRESS: ComplaintStatus.RESOLVED,
            ComplaintStatus.RESOLVED: ComplaintStatus.CLOSED,
        }
        if complaint.status not in transitions or transitions[complaint.status] != body.status:
            raise ValidationException("Invalid status transition")

        updated = await self.repo.update_complaint(
            complaint,
            {
                "status": body.status,
                "resolution_note": body.resolution_note,
                "resolved_by": current_user.id,
            },
        )
        await self.db.refresh(updated)

        if updated.submitted_by:
            background_tasks.add_task(
                _notify_complaint_resolved,
                updated.submitted_by,
                updated.id,
            )

        updated_with_relations = await self.repo.get_complaint_by_id(
            updated.id, school_id
        )
        return self._build_response(
            updated_with_relations or updated,
            current_user=current_user,
        )

    async def create_feedback(
        self,
        body: FeedbackCreate,
        current_user: CurrentUser,
    ) -> FeedbackResponse:
        school_id = self._ensure_school(current_user)
        feedback = await self.repo.create_feedback(
            {
                "user_id": current_user.id,
                "feedback_type": body.feedback_type,
                "rating": body.rating,
                "comment": body.comment,
                "school_id": school_id,
            }
        )
        await self.db.refresh(feedback)
        return FeedbackResponse.model_validate(feedback)

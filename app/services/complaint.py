import uuid
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import select, and_
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
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority, ComplaintStatus

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

    def _build_response(self, complaint) -> ComplaintResponse:
        data = ComplaintResponse.model_validate(complaint)
        if complaint.attachment_key:
            data.attachment_url = minio_client.generate_presigned_url(
                COMPLAINTS_BUCKET, complaint.attachment_key
            )
        if complaint.is_anonymous:
            data.submitted_by = None
        return data

    async def create_complaint(
        self,
        body: ComplaintCreate,
        current_user: CurrentUser,
    ) -> ComplaintResponse:
        school_id = self._ensure_school(current_user)

        submitted_by = None if body.is_anonymous else current_user.id

        complaint = await self.repo.create_complaint(
            {
                "school_id": school_id,
                "submitted_by": submitted_by,
                "category": body.category,
                "description": body.description,
                "attachment_key": body.attachment_key,
                "status": ComplaintStatus.OPEN,
                "resolved_by": None,
                "resolution_note": None,
                "is_anonymous": body.is_anonymous,
            }
        )
        await self.db.commit()
        await self.db.refresh(complaint)
        return self._build_response(complaint)

    async def list_complaints(
        self,
        current_user: CurrentUser,
        status: Optional[ComplaintStatus],
    ) -> ComplaintListResponse:
        school_id = self._ensure_school(current_user)

        submitted_by: Optional[uuid.UUID] = None
        if current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT):
            submitted_by = current_user.id

        complaints = await self.repo.list_complaints(
            school_id=school_id,
            status=status.value if status else None,
            submitted_by=submitted_by,
        )
        return ComplaintListResponse(
            items=[self._build_response(c) for c in complaints],
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
        await self.db.commit()
        await self.db.refresh(updated)

        if updated.submitted_by:
            background_tasks.add_task(
                _notify_complaint_resolved,
                updated.submitted_by,
                updated.id,
            )

        return self._build_response(updated)

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
        await self.db.commit()
        await self.db.refresh(feedback)
        return FeedbackResponse.model_validate(feedback)
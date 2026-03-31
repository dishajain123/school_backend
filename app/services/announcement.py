import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ValidationException, NotFoundException
from app.integrations.minio_client import minio_client
from app.repositories.announcement import AnnouncementRepository
from app.repositories.notification import NotificationRepository
from app.schemas.announcement import (
    AnnouncementCreate,
    AnnouncementUpdate,
    AnnouncementResponse,
    AnnouncementListResponse,
)
from app.utils.enums import RoleEnum, NotificationType, NotificationPriority

ANNOUNCEMENT_BUCKET = "documents"


async def _notify_announcement(
    db: AsyncSession,
    school_id: uuid.UUID,
    announcement_id: uuid.UUID,
    title: str,
    target_role: Optional[RoleEnum],
    target_standard_id: Optional[uuid.UUID],
) -> None:
    from app.models.user import User
    from app.models.student import Student
    from app.models.parent import Parent

    user_ids: set[uuid.UUID] = set()

    if target_role in (RoleEnum.STUDENT, RoleEnum.PARENT) and target_standard_id:
        result = await db.execute(
            select(Student.user_id, Student.parent_id).where(
                and_(
                    Student.school_id == school_id,
                    Student.standard_id == target_standard_id,
                )
            )
        )
        rows = result.all()
        parent_ids: set[uuid.UUID] = set()
        for student_user_id, parent_id in rows:
            if target_role == RoleEnum.STUDENT and student_user_id:
                user_ids.add(student_user_id)
            if target_role == RoleEnum.PARENT and parent_id:
                parent_ids.add(parent_id)

        if target_role == RoleEnum.PARENT and parent_ids:
            parent_result = await db.execute(
                select(Parent.user_id).where(Parent.id.in_(list(parent_ids)))
            )
            for (parent_user_id,) in parent_result:
                if parent_user_id:
                    user_ids.add(parent_user_id)

    else:
        # General announcement or role-targeted without standard
        stmt = select(User.id).where(User.school_id == school_id)
        if target_role:
            stmt = stmt.where(User.role == target_role)
        result = await db.execute(stmt)
        user_ids.update([row[0] for row in result.all()])

    if not user_ids:
        return

    notification_repo = NotificationRepository(db)
    for user_id in user_ids:
        await notification_repo.create(
            {
                "user_id": user_id,
                "title": "Announcement",
                "body": title,
                "type": NotificationType.ANNOUNCEMENT,
                "priority": NotificationPriority.MEDIUM,
                "reference_id": announcement_id,
            }
        )
    await db.commit()


class AnnouncementService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AnnouncementRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    def _build_response(self, announcement) -> AnnouncementResponse:
        data = AnnouncementResponse.model_validate(announcement)
        if announcement.attachment_key:
            data.attachment_url = minio_client.generate_presigned_url(
                ANNOUNCEMENT_BUCKET, announcement.attachment_key
            )
        return data

    async def create_announcement(
        self,
        body: AnnouncementCreate,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> AnnouncementResponse:
        school_id = self._ensure_school(current_user)

        if body.target_standard_id and not body.target_role:
            # standard-specific without a role is allowed (all roles in that standard)
            pass

        announcement = await self.repo.create(
            {
                "title": body.title,
                "body": body.body,
                "type": body.type,
                "created_by": current_user.id,
                "target_role": body.target_role,
                "target_standard_id": body.target_standard_id,
                "attachment_key": body.attachment_key,
                "published_at": datetime.now(timezone.utc),
                "is_active": True,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(announcement)

        background_tasks.add_task(
            _notify_announcement,
            self.db,
            school_id,
            announcement.id,
            announcement.title,
            body.target_role,
            body.target_standard_id,
        )

        return self._build_response(announcement)

    async def list_announcements(
        self,
        current_user: CurrentUser,
        include_inactive: bool = False,
    ) -> AnnouncementListResponse:
        school_id = self._ensure_school(current_user)

        from app.models.student import Student

        standard_ids: Optional[list[uuid.UUID]] = None
        standard_id: Optional[uuid.UUID] = None
        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.standard_id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            standard_id = result.scalar_one_or_none()
            standard_ids = [standard_id] if standard_id else []

        elif current_user.role == RoleEnum.PARENT:
            result = await self.db.execute(
                select(Student.standard_id).where(
                    and_(
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == school_id,
                    )
                )
            )
            standards = [row[0] for row in result.all() if row[0] is not None]
            standard_ids = list(dict.fromkeys(standards))
            standard_id = standard_ids[0] if standard_ids else None

        announcements = await self.repo.list_for_school(
            school_id=school_id,
            include_inactive=include_inactive and current_user.role == RoleEnum.PRINCIPAL,
        )

        filtered = []
        for a in announcements:
            if a.target_role and a.target_role != current_user.role:
                continue

            if a.target_standard_id:
                if current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT):
                    if not standard_ids:
                        continue
                    if a.target_standard_id not in standard_ids:
                        continue
            filtered.append(a)

        return AnnouncementListResponse(
            items=[self._build_response(a) for a in filtered],
            total=len(filtered),
        )

    async def update_announcement(
        self,
        announcement_id: uuid.UUID,
        body: AnnouncementUpdate,
        current_user: CurrentUser,
    ) -> AnnouncementResponse:
        school_id = self._ensure_school(current_user)
        announcement = await self.repo.get_by_id(announcement_id, school_id)
        if not announcement:
            raise NotFoundException("Announcement")

        update_data = body.model_dump(exclude_none=True)
        updated = await self.repo.update(announcement, update_data)
        await self.db.commit()
        await self.db.refresh(updated)
        return self._build_response(updated)

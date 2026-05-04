import uuid
from datetime import datetime, timezone
from typing import Optional  # FIX: was missing — caused NameError inside list_announcements

from fastapi import BackgroundTasks
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ValidationException, NotFoundException
from app.integrations.minio_client import minio_client
from app.repositories.announcement import AnnouncementRepository
from app.repositories.notification import NotificationRepository
from app.repositories.teacher_class_subject import TeacherClassSubjectRepository
from app.services.audit_log import AuditLogService
from app.services.assignment import _get_teacher_id
from app.schemas.announcement import (
    AnnouncementCreate,
    AnnouncementUpdate,
    AnnouncementResponse,
    AnnouncementListResponse,
)
from app.utils.enums import (
    RoleEnum,
    NotificationType,
    NotificationPriority,
    AuditAction,
)

ANNOUNCEMENT_BUCKET = "documents"


async def _notify_announcement(
    school_id: uuid.UUID,
    announcement_id: uuid.UUID,
    title: str,
    body: str,
    target_role: Optional[RoleEnum],
    target_standard_id: Optional[uuid.UUID],
    target_section: Optional[str],
) -> None:
    """Opens its own DB session — never reuses the request session."""
    from app.db.session import AsyncSessionLocal
    from app.models.user import User
    from app.models.student import Student
    from app.models.parent import Parent
    from app.models.teacher import Teacher
    from app.models.teacher_class_subject import TeacherClassSubject

    async with AsyncSessionLocal() as db:
        user_ids: set[uuid.UUID] = set()

        if target_role in (RoleEnum.STUDENT, RoleEnum.PARENT) and target_standard_id:
            normalized_section = (target_section or "").strip()
            result = await db.execute(
                select(Student.user_id, Student.parent_id).where(
                    and_(
                        Student.school_id == school_id,
                        Student.standard_id == target_standard_id,
                        (
                            Student.section == normalized_section
                            if normalized_section
                            else True
                        ),
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

        elif target_role == RoleEnum.TEACHER and target_standard_id:
            normalized_section = (target_section or "").strip()
            teacher_rows = await db.execute(
                select(Teacher.user_id)
                .join(
                    TeacherClassSubject,
                    TeacherClassSubject.teacher_id == Teacher.id,
                )
                .where(
                    and_(
                        Teacher.school_id == school_id,
                        TeacherClassSubject.standard_id == target_standard_id,
                        (
                            TeacherClassSubject.section == normalized_section
                            if normalized_section
                            else True
                        ),
                    )
                )
            )
            for (teacher_user_id,) in teacher_rows.all():
                if teacher_user_id:
                    user_ids.add(teacher_user_id)

        elif target_role is None and target_standard_id:
            normalized_section = (target_section or "").strip()
            student_rows = await db.execute(
                select(Student.user_id, Student.parent_id).where(
                    and_(
                        Student.school_id == school_id,
                        Student.standard_id == target_standard_id,
                        (
                            Student.section == normalized_section
                            if normalized_section
                            else True
                        ),
                    )
                )
            )
            parent_ids: set[uuid.UUID] = set()
            for student_user_id, parent_id in student_rows.all():
                if student_user_id:
                    user_ids.add(student_user_id)
                if parent_id:
                    parent_ids.add(parent_id)

            if parent_ids:
                parent_rows = await db.execute(
                    select(Parent.user_id).where(Parent.id.in_(list(parent_ids)))
                )
                for (parent_user_id,) in parent_rows.all():
                    if parent_user_id:
                        user_ids.add(parent_user_id)

            teacher_rows = await db.execute(
                select(Teacher.user_id)
                .join(
                    TeacherClassSubject,
                    TeacherClassSubject.teacher_id == Teacher.id,
                )
                .where(
                    and_(
                        Teacher.school_id == school_id,
                        TeacherClassSubject.standard_id == target_standard_id,
                        (
                            TeacherClassSubject.section == normalized_section
                            if normalized_section
                            else True
                        ),
                    )
                )
            )
            for (teacher_user_id,) in teacher_rows.all():
                if teacher_user_id:
                    user_ids.add(teacher_user_id)
        else:
            stmt = select(User.id).where(User.school_id == school_id)
            if target_role:
                stmt = stmt.where(User.role == target_role)
            result = await db.execute(stmt)
            user_ids.update([row[0] for row in result.all()])

        if not user_ids:
            return

        short_body = " ".join(body.split()).strip()
        if len(short_body) > 120:
            short_body = f"{short_body[:117]}..."
        if not short_body:
            short_body = title

        notification_repo = NotificationRepository(db)
        for user_id in user_ids:
            await notification_repo.create(
                {
                    "user_id": user_id,
                    "title": title,
                    "body": short_body,
                    "type": NotificationType.ANNOUNCEMENT,
                    "priority": NotificationPriority.HIGH
                    if "urgent" in title.lower()
                    else NotificationPriority.MEDIUM,
                    "reference_id": announcement_id,
                }
            )
        await db.commit()


class AnnouncementService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AnnouncementRepository(db)
        self.audit_service = AuditLogService(db)

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

    async def _assert_teacher_target_scope(
        self,
        *,
        school_id: uuid.UUID,
        current_user: CurrentUser,
        target_standard_id: Optional[uuid.UUID],
        target_section: Optional[str],
    ) -> None:
        if current_user.role != RoleEnum.TEACHER:
            return
        if target_standard_id is None:
            raise ValidationException("Teachers must select an assigned class")

        teacher_id = await _get_teacher_id(self.db, current_user.id, school_id)
        assignments, _ = await TeacherClassSubjectRepository(self.db).list_by_teacher(
            teacher_id=teacher_id,
            academic_year_id=None,
        )
        normalized_section = (target_section or "").strip()
        has_scope = any(
            assignment.standard_id == target_standard_id
            and (
                not normalized_section
                or (assignment.section or "").strip() == normalized_section
            )
            for assignment in assignments
        )
        if not has_scope:
            raise ValidationException(
                "Teachers can target only assigned class/section announcements"
            )

    async def create_announcement(
        self,
        body: AnnouncementCreate,
        current_user: CurrentUser,
        background_tasks: BackgroundTasks,
    ) -> AnnouncementResponse:
        school_id = self._ensure_school(current_user)
        normalized_section = (body.target_section or "").strip() or None
        await self._assert_teacher_target_scope(
            school_id=school_id,
            current_user=current_user,
            target_standard_id=body.target_standard_id,
            target_section=normalized_section,
        )

        announcement = await self.repo.create(
            {
                "title": body.title,
                "body": body.body,
                "type": body.type,
                "created_by": current_user.id,
                "target_role": body.target_role,
                "target_standard_id": body.target_standard_id,
                "target_section": normalized_section,
                "attachment_key": body.attachment_key,
                "published_at": datetime.now(timezone.utc),
                "is_active": True,
                "school_id": school_id,
            }
        )
        await self.db.refresh(announcement)
        await self.audit_service.log(
            action=AuditAction.ANNOUNCEMENT_CREATED,
            actor_id=current_user.id,
            target_user_id=None,
            entity_type="Announcement",
            entity_id=str(announcement.id),
            description=f"Announcement created: {announcement.title}",
            before_state=None,
            after_state={
                "title": announcement.title,
                "type": announcement.type.value,
                "target_role": announcement.target_role.value
                if announcement.target_role
                else None,
                "target_standard_id": str(announcement.target_standard_id)
                if announcement.target_standard_id
                else None,
                "target_section": announcement.target_section,
                "is_active": announcement.is_active,
            },
            school_id=school_id,
        )

        background_tasks.add_task(
            _notify_announcement,
            school_id,
            announcement.id,
            announcement.title,
            announcement.body,
            body.target_role,
            body.target_standard_id,
            normalized_section,
        )

        return self._build_response(announcement)

    async def list_announcements(
        self,
        current_user: CurrentUser,
        include_inactive: bool = False,
        target_role: Optional[RoleEnum] = None,
        target_standard_id: Optional[uuid.UUID] = None,
        target_section: Optional[str] = None,
    ) -> AnnouncementListResponse:
        school_id = self._ensure_school(current_user)

        from app.models.student import Student
        from app.models.teacher import Teacher
        from app.models.teacher_class_subject import TeacherClassSubject

        # FIX: these variables use Optional — which is now properly imported above.
        standard_ids: Optional[list[uuid.UUID]] = None
        standard_id: Optional[uuid.UUID] = None
        standard_sections: set[tuple[uuid.UUID, str]] = set()
        normalized_query_section = (target_section or "").strip() or None

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
            section_result = await self.db.execute(
                select(Student.section).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            student_section = section_result.scalar_one_or_none()
            if standard_id and student_section and student_section.strip():
                standard_sections.add((standard_id, student_section.strip()))

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
            child_rows = await self.db.execute(
                select(Student.standard_id, Student.section).where(
                    and_(
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == school_id,
                    )
                )
            )
            for sid, section in child_rows.all():
                if sid and section and section.strip():
                    standard_sections.add((sid, section.strip()))
        elif current_user.role == RoleEnum.TEACHER:
            t_row = await self.db.execute(
                select(Teacher.id).where(
                    and_(
                        Teacher.user_id == current_user.id,
                        Teacher.school_id == school_id,
                    )
                )
            )
            teacher_id = t_row.scalar_one_or_none()
            if teacher_id:
                std_rows = await self.db.execute(
                    select(TeacherClassSubject.standard_id).where(
                        TeacherClassSubject.teacher_id == teacher_id
                    )
                )
                standard_ids = list(
                    dict.fromkeys([sid for (sid,) in std_rows.all() if sid is not None])
                )
                section_rows = await self.db.execute(
                    select(TeacherClassSubject.standard_id, TeacherClassSubject.section)
                    .where(TeacherClassSubject.teacher_id == teacher_id)
                )
                for sid, section in section_rows.all():
                    if sid and section and section.strip():
                        standard_sections.add((sid, section.strip()))
            else:
                standard_ids = []

        announcements = await self.repo.list_for_school(
            school_id=school_id,
            include_inactive=include_inactive
            and current_user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN),
            target_role=target_role,
            target_standard_id=target_standard_id,
            target_section=normalized_query_section,
        )

        filtered = []
        for a in announcements:
            # Admin views (principal/superadmin) must see all school announcements,
            # including role-targeted/class-targeted ones.
            if current_user.role not in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN):
                if a.target_role and a.target_role != current_user.role:
                    continue

            if a.target_standard_id and current_user.role not in (
                RoleEnum.PRINCIPAL,
                RoleEnum.SUPERADMIN,
            ):
                if current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT, RoleEnum.TEACHER):
                    if not standard_ids:
                        continue
                    if a.target_standard_id not in standard_ids:
                        continue
            if (
                a.target_section
                and current_user.role
                not in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)
            ):
                if not a.target_standard_id:
                    continue
                if (a.target_standard_id, a.target_section.strip()) not in standard_sections:
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

        update_data = body.model_dump(exclude_unset=True)
        if "target_section" in update_data:
            update_data["target_section"] = (
                (update_data.get("target_section") or "").strip() or None
            )
        next_standard_id = update_data.get(
            "target_standard_id", announcement.target_standard_id
        )
        next_section = update_data.get("target_section", announcement.target_section)
        await self._assert_teacher_target_scope(
            school_id=school_id,
            current_user=current_user,
            target_standard_id=next_standard_id,
            target_section=next_section,
        )
        before_state = {
            "title": announcement.title,
            "body": announcement.body,
            "type": announcement.type.value,
            "target_role": announcement.target_role.value
            if announcement.target_role
            else None,
            "target_standard_id": str(announcement.target_standard_id)
            if announcement.target_standard_id
            else None,
            "target_section": announcement.target_section,
            "attachment_key": announcement.attachment_key,
            "is_active": announcement.is_active,
        }
        updated = await self.repo.update(announcement, update_data)
        await self.db.refresh(updated)
        await self.audit_service.log(
            action=AuditAction.ANNOUNCEMENT_UPDATED,
            actor_id=current_user.id,
            target_user_id=None,
            entity_type="Announcement",
            entity_id=str(updated.id),
            description=f"Announcement updated: {updated.title}",
            before_state=before_state,
            after_state={
                "title": updated.title,
                "body": updated.body,
                "type": updated.type.value,
                "target_role": updated.target_role.value if updated.target_role else None,
                "target_standard_id": str(updated.target_standard_id)
                if updated.target_standard_id
                else None,
                "target_section": updated.target_section,
                "attachment_key": updated.attachment_key,
                "is_active": updated.is_active,
            },
            school_id=school_id,
        )
        return self._build_response(updated)

    async def get_announcement_by_id(
        self,
        announcement_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> AnnouncementResponse:
        school_id = self._ensure_school(current_user)
        obj = await self.repo.get_by_id(announcement_id, school_id)
        if not obj:
            raise NotFoundException("Announcement")
        if not obj.is_active and current_user.role not in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN):
            raise NotFoundException("Announcement")
        return self._build_response(obj)

    async def delete_announcement(
        self,
        announcement_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> None:
        school_id = self._ensure_school(current_user)
        announcement = await self.repo.get_by_id(announcement_id, school_id)
        if not announcement:
            raise NotFoundException("Announcement")
        before_state = {
            "title": announcement.title,
            "body": announcement.body,
            "type": announcement.type.value,
            "target_role": announcement.target_role.value
            if announcement.target_role
            else None,
            "target_standard_id": str(announcement.target_standard_id)
            if announcement.target_standard_id
            else None,
            "target_section": announcement.target_section,
            "is_active": announcement.is_active,
        }
        await self.repo.update(announcement, {"is_active": False})
        await self.audit_service.log(
            action=AuditAction.ANNOUNCEMENT_DELETED,
            actor_id=current_user.id,
            target_user_id=None,
            entity_type="Announcement",
            entity_id=str(announcement.id),
            description=f"Announcement deleted: {announcement.title}",
            before_state=before_state,
            after_state={**before_state, "is_active": False},
            school_id=school_id,
        )

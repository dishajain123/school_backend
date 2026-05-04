import uuid
import math
import re
from typing import Optional

from fastapi import UploadFile, HTTPException
from sqlalchemy import select, and_, or_, func, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException
from app.repositories.chat import ChatRepository
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationListResponse,
    ChatUserOption,
    ChatUserListResponse,
    MessageCreate,
    MessageResponse,
    MessageListResponse,
    MessageReactionSummary,
    MessageReactionUpdateResponse,
)
from app.integrations.minio_client import minio_client
from app.services.academic_year import get_active_year
from app.utils.enums import RoleEnum, ConversationType

CHAT_BUCKET = "chat-files"


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ChatRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    @staticmethod
    def _user_display_name(user) -> str:
        if user is None:
            return "Unknown"
        full_name = (getattr(user, "full_name", None) or "").strip()
        if full_name:
            return full_name
        email = (getattr(user, "email", None) or "").strip()
        if email:
            local_part = email.split("@", 1)[0]
            cleaned = re.sub(r"[\._\-]+", " ", local_part).strip()
            if cleaned:
                return " ".join(word[:1].upper() + word[1:] for word in cleaned.split())
            return local_part
        phone = (getattr(user, "phone", None) or "").strip()
        if phone:
            return phone
        role = getattr(user, "role", None)
        if role is not None:
            role_value = role.value if hasattr(role, "value") else str(role)
            return role_value.replace("_", " ").title()
        return "Unknown"

    @classmethod
    def _display_name_from_fields(
        cls,
        *,
        full_name: Optional[str],
        email: Optional[str],
        phone: Optional[str],
        role,
    ) -> str:
        pseudo_user = type(
            "_ChatDisplayUser",
            (),
            {"full_name": full_name, "email": email, "phone": phone, "role": role},
        )()
        return cls._user_display_name(pseudo_user)

    def _conversation_display_name(self, conversation, current_user_id: uuid.UUID) -> str:
        if conversation.type == ConversationType.ONE_TO_ONE:
            for participant in conversation.participants or []:
                if participant.user_id == current_user_id:
                    continue
                user = participant.user
                if user is not None:
                    return self._user_display_name(user)
            # Fallback: if participant resolution fails, keep a custom name if present.
            if conversation.name and conversation.name.strip():
                return conversation.name.strip()
            return "Direct Message"

        if conversation.name and conversation.name.strip():
            return conversation.name.strip()

        return "Group Chat"

    def _to_conversation_response(self, conversation, current_user_id: uuid.UUID) -> ConversationResponse:
        base = ConversationResponse.model_validate(conversation)
        return base.model_copy(
            update={
                "display_name": self._conversation_display_name(
                    conversation, current_user_id
                )
            }
        )

    @staticmethod
    def _reaction_summary(reactions) -> list[MessageReactionSummary]:
        counts: dict[str, int] = {}
        for reaction in reactions or []:
            emoji = (reaction.emoji or "").strip()
            if not emoji:
                continue
            counts[emoji] = counts.get(emoji, 0) + 1
        return [
            MessageReactionSummary(emoji=emoji, count=count)
            for emoji, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _to_message_response(self, message, current_user_id: uuid.UUID) -> MessageResponse:
        my_reaction = None
        for reaction in message.reactions or []:
            if reaction.user_id == current_user_id:
                my_reaction = reaction.emoji
                break
        return MessageResponse(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_id=message.sender_id,
            content=message.content,
            message_type=message.message_type,
            file_key=message.file_key,
            sent_at=message.sent_at,
            school_id=message.school_id,
            created_at=message.created_at,
            updated_at=message.updated_at,
            reactions=self._reaction_summary(message.reactions),
            my_reaction=my_reaction,
        )

    @staticmethod
    def _allowed_one_to_one_targets(role: RoleEnum) -> tuple[RoleEnum, ...]:
        if role == RoleEnum.TEACHER:
            return (
                RoleEnum.PARENT,
                RoleEnum.STUDENT,
                RoleEnum.PRINCIPAL,
                RoleEnum.TRUSTEE,
            )
        if role == RoleEnum.PRINCIPAL:
            return (
                RoleEnum.TEACHER,
                RoleEnum.PARENT,
                RoleEnum.STUDENT,
                RoleEnum.TRUSTEE,
            )
        if role == RoleEnum.TRUSTEE:
            return (RoleEnum.PRINCIPAL, RoleEnum.TEACHER)
        if role == RoleEnum.PARENT:
            return (RoleEnum.TEACHER, RoleEnum.PRINCIPAL)
        if role == RoleEnum.STUDENT:
            return (RoleEnum.TEACHER, RoleEnum.PRINCIPAL)
        if role == RoleEnum.SUPERADMIN:
            return (
                RoleEnum.PRINCIPAL,
                RoleEnum.TRUSTEE,
                RoleEnum.TEACHER,
            )
        return tuple()

    async def _teacher_allowed_group_user_ids(
        self,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID],
    ) -> set[uuid.UUID]:
        school_id = self._ensure_school(current_user)
        from app.models.user import User
        from app.models.student import Student
        from app.models.parent import Parent
        from app.models.teacher import Teacher
        from app.models.teacher_class_subject import TeacherClassSubject

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
            return set()

        resolved_year_id = academic_year_id
        if resolved_year_id is None:
            resolved_year_id = (await get_active_year(school_id, self.db)).id

        assignment_rows = (
            await self.db.execute(
                select(
                    TeacherClassSubject.standard_id,
                    func.upper(func.trim(TeacherClassSubject.section)).label("section"),
                )
                .where(
                    TeacherClassSubject.teacher_id == teacher_id,
                    TeacherClassSubject.academic_year_id == resolved_year_id,
                )
                .distinct()
            )
        ).all()
        allowed_pairs = [(row.standard_id, row.section) for row in assignment_rows]
        if not allowed_pairs:
            return set()

        student_rows = (
            await self.db.execute(
                select(User.id)
                .join(Student, Student.user_id == User.id)
                .where(
                    User.school_id == school_id,
                    User.is_active.is_(True),
                    User.role == RoleEnum.STUDENT,
                    Student.school_id == school_id,
                    Student.academic_year_id == resolved_year_id,
                    tuple_(
                        Student.standard_id,
                        func.upper(func.trim(Student.section)),
                    ).in_(allowed_pairs),
                )
                .distinct()
            )
        ).all()
        parent_rows = (
            await self.db.execute(
                select(User.id)
                .join(Parent, Parent.user_id == User.id)
                .join(Student, Student.parent_id == Parent.id)
                .where(
                    User.school_id == school_id,
                    User.is_active.is_(True),
                    User.role == RoleEnum.PARENT,
                    Parent.school_id == school_id,
                    Student.school_id == school_id,
                    Student.academic_year_id == resolved_year_id,
                    tuple_(
                        Student.standard_id,
                        func.upper(func.trim(Student.section)),
                    ).in_(allowed_pairs),
                )
                .distinct()
            )
        ).all()
        return {row.id for row in student_rows} | {row.id for row in parent_rows}

    async def create_conversation(
        self,
        body: ConversationCreate,
        current_user: CurrentUser,
    ) -> ConversationResponse:
        school_id = self._ensure_school(current_user)

        participant_ids = list(dict.fromkeys(body.participant_ids))
        if current_user.id not in participant_ids:
            participant_ids.append(current_user.id)

        if body.type == ConversationType.ONE_TO_ONE:
            if len(participant_ids) != 2:
                raise ValidationException("One-to-one conversation requires exactly 2 participants")

            other_user_id = participant_ids[0] if participant_ids[1] == current_user.id else participant_ids[1]

            from app.models.user import User

            result = await self.db.execute(
                select(User.id, User.role, User.school_id).where(User.id == other_user_id)
            )
            other = result.one_or_none()
            if not other:
                raise NotFoundException("User")
            if other.school_id != school_id:
                raise ForbiddenException("User is not in your school")

            # Access rules
            allowed_targets = self._allowed_one_to_one_targets(current_user.role)
            if other.role not in allowed_targets:
                raise ForbiddenException("Chat not allowed with this role")

            existing = await self.repo.find_one_to_one(
                school_id=school_id,
                user_a=current_user.id,
                user_b=other_user_id,
            )
            if existing:
                existing_full = await self.repo.get_conversation_by_id(existing.id, school_id)
                if existing_full is None:
                    raise NotFoundException("Conversation")
                return self._to_conversation_response(existing_full, current_user.id)
        elif body.type == ConversationType.GROUP and current_user.role == RoleEnum.TEACHER:
            non_self_participants = [u for u in participant_ids if u != current_user.id]
            if not non_self_participants:
                raise ValidationException("Group conversation requires at least 1 recipient")

            from app.models.user import User
            rows = (
                await self.db.execute(
                    select(User.id, User.role, User.school_id, User.is_active).where(
                        User.id.in_(non_self_participants)
                    )
                )
            ).all()
            if len(rows) != len(set(non_self_participants)):
                raise NotFoundException("One or more users")

            for row in rows:
                if row.school_id != school_id or not row.is_active:
                    raise ForbiddenException("User is not in your school or inactive")
                if row.role not in (RoleEnum.STUDENT, RoleEnum.PARENT):
                    raise ForbiddenException(
                        "Teacher group chat recipients can only be students or parents"
                    )

            allowed_user_ids = await self._teacher_allowed_group_user_ids(
                current_user=current_user,
                academic_year_id=body.academic_year_id,
            )
            if not allowed_user_ids:
                raise ForbiddenException(
                    "No eligible students/parents found in your assigned classes"
                )
            disallowed = [
                row.id for row in rows if row.id not in allowed_user_ids
            ]
            if disallowed:
                raise ForbiddenException(
                    "One or more selected recipients are outside your assigned classes"
                )

        conversation = await self.repo.create_conversation(
            {
                "type": body.type,
                "name": body.name,
                "standard_id": body.standard_id,
                "created_by": current_user.id,
                "academic_year_id": body.academic_year_id,
                "school_id": school_id,
            }
        )

        for user_id in participant_ids:
            await self.repo.add_participant(
                {
                    "conversation_id": conversation.id,
                    "user_id": user_id,
                    "is_admin": user_id == current_user.id,
                }
            )

        # commit required before other clients read this conversation (WS / separate HTTP session).
        await self.db.commit()
        full = await self.repo.get_conversation_by_id(conversation.id, school_id)
        if full is None:
            raise NotFoundException("Conversation")
        return self._to_conversation_response(full, current_user.id)

    async def list_chatable_users(
        self,
        current_user: CurrentUser,
        page: int = 1,
        page_size: int = 20,
        query: Optional[str] = None,
        role: Optional[RoleEnum] = None,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        subject_id: Optional[uuid.UUID] = None,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> ChatUserListResponse:
        school_id = self._ensure_school(current_user)
        from app.models.user import User
        from app.models.student import Student
        from app.models.parent import Parent
        from app.models.teacher import Teacher
        from app.models.teacher_class_subject import TeacherClassSubject

        allowed_roles = set(self._allowed_one_to_one_targets(current_user.role))
        if not allowed_roles:
            return ChatUserListResponse(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                total_pages=0,
            )

        if role is not None and role not in allowed_roles:
            raise ForbiddenException("Chat not allowed with this role")

        target_roles = [role] if role is not None else list(allowed_roles)
        filters = [
            User.school_id == school_id,
            User.id != current_user.id,
            User.is_active.is_(True),
            User.role.in_(target_roles),
        ]

        q = (query or "").strip().lower()
        if q:
            filters.append(
                or_(
                    func.lower(User.email).like(f"%{q}%"),
                    func.lower(User.phone).like(f"%{q}%"),
                )
            )

        stmt = select(User.id, User.role, User.full_name, User.email, User.phone).where(and_(*filters))

        normalized_section = (section or "").strip().upper()

        # Teacher scope guard:
        # Teachers can discover only students/parents that belong to their allotted
        # class-section (and optional subject) assignments for the selected year.
        if current_user.role == RoleEnum.TEACHER and role in (RoleEnum.STUDENT, RoleEnum.PARENT):
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
                return ChatUserListResponse(
                    items=[],
                    total=0,
                    page=page,
                    page_size=page_size,
                    total_pages=0,
                )

            resolved_year_id = academic_year_id
            if resolved_year_id is None:
                resolved_year_id = (await get_active_year(school_id, self.db)).id

            assignment_stmt = select(
                TeacherClassSubject.standard_id,
                func.upper(func.trim(TeacherClassSubject.section)).label("section"),
            ).where(
                TeacherClassSubject.teacher_id == teacher_id,
                TeacherClassSubject.academic_year_id == resolved_year_id,
            )
            if standard_id is not None:
                assignment_stmt = assignment_stmt.where(
                    TeacherClassSubject.standard_id == standard_id
                )
            if normalized_section:
                assignment_stmt = assignment_stmt.where(
                    func.upper(func.trim(TeacherClassSubject.section))
                    == normalized_section
                )
            if subject_id is not None:
                assignment_stmt = assignment_stmt.where(
                    TeacherClassSubject.subject_id == subject_id
                )

            assignment_rows = (await self.db.execute(assignment_stmt.distinct())).all()
            allowed_pairs = [(row.standard_id, row.section) for row in assignment_rows]
            if not allowed_pairs:
                return ChatUserListResponse(
                    items=[],
                    total=0,
                    page=page,
                    page_size=page_size,
                    total_pages=0,
                )

            if role == RoleEnum.STUDENT:
                stmt = stmt.join(Student, Student.user_id == User.id).where(
                    Student.school_id == school_id,
                    Student.academic_year_id == resolved_year_id,
                    tuple_(
                        Student.standard_id,
                        func.upper(func.trim(Student.section)),
                    ).in_(allowed_pairs),
                )
                count_stmt = select(func.count()).select_from(stmt.distinct().subquery())
                total = int((await self.db.execute(count_stmt)).scalar_one() or 0)
                stmt = (
                    stmt.distinct()
                    .order_by(User.role.asc(), User.email.asc(), User.phone.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
                rows = (await self.db.execute(stmt)).all()
                items = [
                    ChatUserOption(
                        id=row.id,
                        role=row.role.value if hasattr(row.role, "value") else str(row.role),
                        display_name=self._display_name_from_fields(
                            full_name=row.full_name,
                            email=row.email,
                            phone=row.phone,
                            role=row.role,
                        ),
                        email=row.email,
                        phone=row.phone,
                    )
                    for row in rows
                ]
                return ChatUserListResponse(
                    items=items,
                    total=total,
                    page=page,
                    page_size=page_size,
                    total_pages=math.ceil(total / page_size) if total else 0,
                )

            if role == RoleEnum.PARENT:
                stmt = stmt.join(Parent, Parent.user_id == User.id).where(
                    Parent.school_id == school_id
                )
                stmt = stmt.join(Student, Student.parent_id == Parent.id).where(
                    Student.school_id == school_id,
                    Student.academic_year_id == resolved_year_id,
                    tuple_(
                        Student.standard_id,
                        func.upper(func.trim(Student.section)),
                    ).in_(allowed_pairs),
                )
                count_stmt = select(func.count()).select_from(stmt.distinct().subquery())
                total = int((await self.db.execute(count_stmt)).scalar_one() or 0)
                stmt = (
                    stmt.distinct()
                    .order_by(User.role.asc(), User.email.asc(), User.phone.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
                rows = (await self.db.execute(stmt)).all()
                items = [
                    ChatUserOption(
                        id=row.id,
                        role=row.role.value if hasattr(row.role, "value") else str(row.role),
                        display_name=self._display_name_from_fields(
                            full_name=row.full_name,
                            email=row.email,
                            phone=row.phone,
                            role=row.role,
                        ),
                        email=row.email,
                        phone=row.phone,
                    )
                    for row in rows
                ]
                return ChatUserListResponse(
                    items=items,
                    total=total,
                    page=page,
                    page_size=page_size,
                    total_pages=math.ceil(total / page_size) if total else 0,
                )

        if role == RoleEnum.STUDENT:
            stmt = stmt.join(Student, Student.user_id == User.id).where(
                Student.school_id == school_id
            )
            if standard_id is not None:
                stmt = stmt.where(Student.standard_id == standard_id)
            if normalized_section:
                stmt = stmt.where(func.upper(func.trim(Student.section)) == normalized_section)
            if academic_year_id is not None:
                stmt = stmt.where(Student.academic_year_id == academic_year_id)
        elif role == RoleEnum.PARENT:
            stmt = stmt.join(Parent, Parent.user_id == User.id).where(
                Parent.school_id == school_id
            )
            if standard_id is not None or normalized_section or academic_year_id is not None:
                stmt = stmt.join(Student, Student.parent_id == Parent.id).where(
                    Student.school_id == school_id
                )
                if standard_id is not None:
                    stmt = stmt.where(Student.standard_id == standard_id)
                if normalized_section:
                    stmt = stmt.where(
                        func.upper(func.trim(Student.section)) == normalized_section
                    )
                if academic_year_id is not None:
                    stmt = stmt.where(Student.academic_year_id == academic_year_id)
        elif role == RoleEnum.TEACHER and (
            standard_id is not None
            or subject_id is not None
            or normalized_section
            or academic_year_id is not None
        ):
            stmt = stmt.join(Teacher, Teacher.user_id == User.id).where(
                Teacher.school_id == school_id
            )
            stmt = stmt.join(
                TeacherClassSubject, TeacherClassSubject.teacher_id == Teacher.id
            )
            if standard_id is not None:
                stmt = stmt.where(TeacherClassSubject.standard_id == standard_id)
            if subject_id is not None:
                stmt = stmt.where(TeacherClassSubject.subject_id == subject_id)
            if normalized_section:
                stmt = stmt.where(
                    func.upper(func.trim(TeacherClassSubject.section))
                    == normalized_section
                )
            if academic_year_id is not None:
                stmt = stmt.where(TeacherClassSubject.academic_year_id == academic_year_id)

        count_stmt = select(func.count()).select_from(stmt.distinct().subquery())
        total = int((await self.db.execute(count_stmt)).scalar_one() or 0)

        stmt = (
            stmt.distinct()
            .order_by(User.role.asc(), User.email.asc(), User.phone.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.db.execute(stmt)).all()
        items = [
            ChatUserOption(
                id=row.id,
                role=row.role.value if hasattr(row.role, "value") else str(row.role),
                display_name=self._display_name_from_fields(
                    full_name=row.full_name,
                    email=row.email,
                    phone=row.phone,
                    role=row.role,
                ),
                email=row.email,
                phone=row.phone,
            )
            for row in rows
        ]

        return ChatUserListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    async def list_conversations(
        self, current_user: CurrentUser
    ) -> ConversationListResponse:
        school_id = self._ensure_school(current_user)
        items = await self.repo.list_conversations_for_user(current_user.id, school_id)
        return ConversationListResponse(
            items=[self._to_conversation_response(c, current_user.id) for c in items],
            total=len(items),
        )

    async def list_messages(
        self,
        conversation_id: uuid.UUID,
        current_user: CurrentUser,
        page: int,
        page_size: int,
    ) -> MessageListResponse:
        school_id = self._ensure_school(current_user)
        is_member = await self.repo.is_participant(conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        items, total = await self.repo.list_messages(
            conversation_id=conversation_id,
            school_id=school_id,
            page=page,
            page_size=page_size,
        )
        return MessageListResponse(
            items=[self._to_message_response(m, current_user.id) for m in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    async def send_message(
        self,
        body: MessageCreate,
        current_user: CurrentUser,
    ) -> MessageResponse:
        school_id = self._ensure_school(current_user)
        is_member = await self.repo.is_participant(body.conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        if not body.content and not body.file_key:
            raise ValidationException("content or file_key is required")

        message = await self.repo.create_message(
            {
                "conversation_id": body.conversation_id,
                "sender_id": current_user.id,
                "content": body.content,
                "message_type": body.message_type,
                "file_key": body.file_key,
                "school_id": school_id,
            }
        )
        # commit required before other connections read this message (WS / poll).
        await self.db.commit()
        await self.db.refresh(message)
        hydrated = await self.repo.get_message_by_id(message.id, school_id)
        if hydrated is None:
            raise NotFoundException("Message")
        return self._to_message_response(hydrated, current_user.id)

    async def mark_read(
        self,
        conversation_id: uuid.UUID,
        message_ids: list[uuid.UUID],
        current_user: CurrentUser,
    ) -> int:
        school_id = self._ensure_school(current_user)
        is_member = await self.repo.is_participant(conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        count = 0
        for message_id in message_ids:
            try:
                await self.repo.create_message_read(
                    {
                        "message_id": message_id,
                        "user_id": current_user.id,
                    }
                )
                count += 1
            except Exception:
                continue
        return count

    async def upload_file(
        self,
        conversation_id: uuid.UUID,
        current_user: CurrentUser,
        file: UploadFile,
    ) -> str:
        school_id = self._ensure_school(current_user)
        is_member = await self.repo.is_participant(conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        if not file or not file.filename:
            raise HTTPException(status_code=422, detail="File is required")

        content = await file.read()
        file_key = f"{school_id}/{conversation_id}/{uuid.uuid4()}_{file.filename}"
        minio_client.upload_file(
            bucket=CHAT_BUCKET,
            key=file_key,
            file_bytes=content,
            content_type=file.content_type or "application/octet-stream",
        )
        return file_key

    async def delete_conversation(
        self,
        conversation_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> None:
        school_id = self._ensure_school(current_user)
        conversation = await self.repo.get_conversation_by_id(conversation_id, school_id)
        if conversation is None:
            raise NotFoundException("Conversation")

        if current_user.role not in (RoleEnum.PRINCIPAL, RoleEnum.TEACHER):
            raise ForbiddenException("Only principal and teacher can delete chats")

        is_member = await self.repo.is_participant(conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        await self.repo.delete_conversation(conversation)

    async def react_to_message(
        self,
        message_id: uuid.UUID,
        emoji: str,
        current_user: CurrentUser,
    ) -> MessageReactionUpdateResponse:
        school_id = self._ensure_school(current_user)
        reaction_value = (emoji or "").strip()
        if not reaction_value:
            raise ValidationException("emoji is required")

        if current_user.role not in (
            RoleEnum.PARENT,
            RoleEnum.STUDENT,
            RoleEnum.TEACHER,
            RoleEnum.PRINCIPAL,
        ):
            raise ForbiddenException("Only parent, student, teacher, and principal can react")

        message = await self.repo.get_message_by_id(message_id, school_id)
        if message is None:
            raise NotFoundException("Message")

        is_member = await self.repo.is_participant(message.conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        existing = await self.repo.get_message_reaction(message_id, current_user.id)
        status = "added"
        my_reaction: Optional[str] = reaction_value

        if existing is not None and existing.emoji == reaction_value:
            await self.repo.delete_message_reaction(existing)
            status = "removed"
            my_reaction = None
        elif existing is not None:
            existing.emoji = reaction_value
            status = "updated"
        else:
            await self.repo.create_message_reaction(
                {
                    "message_id": message_id,
                    "user_id": current_user.id,
                    "emoji": reaction_value,
                }
            )

        updated = await self.repo.get_message_by_id(message_id, school_id)
        if updated is None:
            raise NotFoundException("Message")

        return MessageReactionUpdateResponse(
            message_id=updated.id,
            conversation_id=updated.conversation_id,
            status=status,
            reaction=my_reaction,
            reactions=self._reaction_summary(updated.reactions),
            my_reaction=my_reaction,
        )

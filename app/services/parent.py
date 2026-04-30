import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.parent import ParentRepository
from app.repositories.user import UserRepository
from app.schemas.parent import ParentCreate, ParentUpdate
from app.models.parent import Parent
from app.models.student import Student
from app.models.student_year_mapping import StudentYearMapping
from app.models.user import User
from app.core.security import hash_password, verify_password
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ConflictException,
)
from app.core.dependencies import CurrentUser
from app.utils.enums import EnrollmentStatus, RegistrationSource, RoleEnum, UserStatus


class ParentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.parent_repo = ParentRepository(db)
        self.user_repo = UserRepository(db)

    async def _resolve_parent_id(self, current_user: CurrentUser) -> uuid.UUID:
        """
        Resolve parent id reliably from token or DB.
        Some sessions may not carry parent_id in JWT; in that case use user_id.
        """
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        if current_user.parent_id:
            return current_user.parent_id

        parent = await self.parent_repo.get_by_user_id(current_user.id)
        if not parent or parent.school_id != school_id:
            raise NotFoundException(detail="Parent profile not found for this user")
        return parent.id

    @staticmethod
    def _ensure_user_is_active(user: Optional[User], label: str) -> None:
        if not user:
            raise ValidationException(f"{label} user account not found")
        if user.status != UserStatus.ACTIVE or not user.is_active:
            raise ValidationException(
                f"{label} mapping is allowed only for approved active users"
            )

    async def _ensure_students_are_active(self, students: list[Student]) -> None:
        user_ids = [s.user_id for s in students if s.user_id is not None]
        if len(user_ids) != len(students):
            raise ValidationException("All students must be linked to user accounts")

        users_result = await self.db.execute(select(User).where(User.id.in_(user_ids)))
        users = {u.id: u for u in users_result.scalars().all()}
        for student in students:
            user = users.get(student.user_id)
            self._ensure_user_is_active(user, "Student")

    async def _ensure_students_are_enrolled(
        self,
        students: list[Student],
        school_id: uuid.UUID,
    ) -> None:
        student_ids = [student.id for student in students]
        if not student_ids:
            return
        rows = await self.db.execute(
            select(StudentYearMapping.student_id)
            .where(
                StudentYearMapping.school_id == school_id,
                StudentYearMapping.student_id.in_(student_ids),
                StudentYearMapping.status == EnrollmentStatus.ACTIVE,
            )
            .group_by(StudentYearMapping.student_id)
        )
        enrolled_ids = set(rows.scalars().all())
        not_enrolled = [sid for sid in student_ids if sid not in enrolled_ids]
        if not_enrolled:
            raise ValidationException(
                "Student must be enrolled before linking to a parent. "
                f"Enroll student first for: {', '.join(str(sid) for sid in not_enrolled)}"
            )

    async def create_parent(
        self,
        payload: ParentCreate,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Parent:
        normalized_email = payload.user.email.lower().strip()
        normalized_phone = payload.user.phone.strip()

        existing_email = await self.user_repo.get_by_email(normalized_email)
        existing_phone = await self.user_repo.get_by_phone(normalized_phone)

        if existing_email and existing_phone and existing_email.id != existing_phone.id:
            raise ConflictException(
                detail="Email and phone belong to different accounts"
            )

        existing_user = existing_email or existing_phone

        if existing_user:
            if existing_user.role != RoleEnum.PARENT:
                raise ConflictException(
                    detail="This email or phone is already used by a non-parent account"
                )
            if existing_user.school_id != school_id:
                raise ConflictException(
                    detail="Parent account belongs to a different school"
                )

            existing_parent = await self.parent_repo.get_by_user_id(existing_user.id)
            if existing_parent:
                update_payload = {}
                if payload.occupation and payload.occupation != existing_parent.occupation:
                    update_payload["occupation"] = payload.occupation
                if payload.relation != existing_parent.relation:
                    update_payload["relation"] = payload.relation
                if update_payload:
                    await self.parent_repo.update(existing_parent, update_payload)
                    await self.db.commit()
                return await self.parent_repo.get_by_id(existing_parent.id, school_id)  # type: ignore[return-value]

            parent = await self.parent_repo.create(
                {
                    "user_id": existing_user.id,
                    "school_id": school_id,
                    "occupation": payload.occupation,
                    "relation": payload.relation,
                }
            )
            await self.db.commit()
            await self.db.refresh(parent)
            return await self.parent_repo.get_by_id(parent.id, school_id)  # type: ignore[return-value]

        user = await self.user_repo.create(
            {
                "email": normalized_email,
                "phone": normalized_phone,
                "hashed_password": hash_password(payload.user.password),
                "role": RoleEnum.PARENT,
                "school_id": school_id,
                "status": UserStatus.PENDING_APPROVAL,
                "registration_source": RegistrationSource.ADMIN_CREATED,
                "is_active": False,
            }
        )

        parent = await self.parent_repo.create(
            {
                "user_id": user.id,
                "school_id": school_id,
                "occupation": payload.occupation,
                "relation": payload.relation,
            }
        )

        await self.db.commit()
        await self.db.refresh(parent)

        # Reload with user eager-loaded
        return await self.parent_repo.get_by_id(parent.id, school_id)  # type: ignore[return-value]

    async def get_parent(
        self,
        parent_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Parent:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        parent = await self.parent_repo.get_by_id(parent_id, school_id)
        if not parent:
            raise NotFoundException(detail="Parent not found")

        # A PARENT role user may only view their own profile
        if current_user.role == RoleEnum.PARENT:
            if current_user.parent_id != parent.id:
                from app.core.exceptions import ForbiddenException
                raise ForbiddenException(detail="Access denied")

        return parent

    async def list_parents(
        self,
        school_id: uuid.UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[Parent], int]:
        return await self.parent_repo.list_by_school(school_id, page, page_size)

    async def update_parent(
        self,
        parent_id: uuid.UUID,
        payload: ParentUpdate,
        current_user: CurrentUser,
    ) -> Parent:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        parent = await self.parent_repo.get_by_id(parent_id, school_id)
        if not parent:
            raise NotFoundException(detail="Parent not found")

        update_data = payload.model_dump(exclude_unset=True)
        updated = await self.parent_repo.update(parent, update_data)
        await self.db.commit()
        await self.db.refresh(updated)
        return await self.parent_repo.get_by_id(parent_id, school_id)  # type: ignore[return-value]

    async def get_children(
        self,
        parent_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> tuple[uuid.UUID, list[Student]]:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        parent = await self.parent_repo.get_by_id(parent_id, school_id)
        if not parent:
            raise NotFoundException(detail="Parent not found")

        # PARENT role may only see their own children
        if current_user.role == RoleEnum.PARENT:
            if current_user.parent_id != parent.id:
                from app.core.exceptions import ForbiddenException
                raise ForbiddenException(detail="Access denied")

        children = await self.parent_repo.get_children(parent_id, school_id)
        return parent.id, children

    async def link_child_for_current_parent(
        self,
        current_user: CurrentUser,
        student_id: Optional[uuid.UUID] = None,
        admission_number: Optional[str] = None,
        student_email: Optional[str] = None,
        student_phone: Optional[str] = None,
        student_password: Optional[str] = None,
    ) -> tuple[uuid.UUID, list[Student]]:
        if current_user.role != RoleEnum.PARENT:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException(detail="Only parents can access this endpoint")

        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        parent_id = await self._resolve_parent_id(current_user)
        parent_profile = await self.parent_repo.get_by_id(parent_id, school_id)
        if not parent_profile:
            raise NotFoundException(detail="Parent profile not found")
        self._ensure_user_is_active(parent_profile.user, "Parent")

        if not student_id and not admission_number:
            raise ValidationException("Provide student_id or admission_number")

        student_query = select(Student).where(Student.school_id == school_id)
        if student_id:
            student_query = student_query.where(Student.id == student_id)
        else:
            student_query = student_query.where(
                Student.admission_number == admission_number.strip()  # type: ignore[union-attr]
            )
        student = (await self.db.execute(student_query)).scalar_one_or_none()
        if not student:
            raise NotFoundException(detail="Student not found")
        await self._ensure_students_are_active([student])
        await self._ensure_students_are_enrolled([student], school_id)

        if student.parent_id == parent_id:
            # Idempotent behavior: return current links when child is already
            # linked to the same parent instead of failing with 409.
            children = await self.parent_repo.get_children(parent_id, school_id)
            return parent_id, children

        if not student_password or (not student_email and not student_phone):
            raise ConflictException(
                detail=(
                    "This student is linked to another parent. "
                    "Provide student credentials to confirm and relink."
                )
            )

        credential_query = select(User).where(User.school_id == school_id)
        if student_email:
            credential_query = credential_query.where(
                User.email == student_email.lower().strip()
            )
        else:
            credential_query = credential_query.where(User.phone == student_phone)
        student_user = (await self.db.execute(credential_query)).scalar_one_or_none()
        if not student_user:
            raise ValidationException("Student credentials are invalid")
        if student_user.role != RoleEnum.STUDENT:
            raise ValidationException("Provided credentials are not for a student account")
        if not student_user.hashed_password or not verify_password(
            student_password,
            student_user.hashed_password,
        ):
            raise ValidationException("Student credentials are invalid")
        if student.user_id != student_user.id:
            raise ValidationException("Provided credentials do not match this student")

        student.parent_id = parent_id
        await self.db.flush()
        await self.db.commit()

        children = await self.parent_repo.get_children(parent_id, school_id)
        return parent_id, children

    async def get_my_children(
        self,
        current_user: CurrentUser,
    ) -> tuple[uuid.UUID, list[Student]]:
        if current_user.role != RoleEnum.PARENT:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException(detail="Only parents can access this endpoint")

        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        parent_id = await self._resolve_parent_id(current_user)
        children = await self.parent_repo.get_children(parent_id, school_id)
        return parent_id, children

    async def assign_children(
        self,
        parent_id: uuid.UUID,
        student_ids: list[uuid.UUID],
        current_user: CurrentUser,
    ) -> tuple[uuid.UUID, list[Student]]:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        parent = await self.parent_repo.get_by_id(parent_id, school_id)
        if not parent:
            raise NotFoundException(detail="Parent not found")
        self._ensure_user_is_active(parent.user, "Parent")

        unique_ids = list(dict.fromkeys(student_ids))
        if not unique_ids:
            children = await self.parent_repo.get_children(parent_id, school_id)
            return parent.id, children

        students_result = await self.db.execute(
            select(Student).where(
                Student.school_id == school_id,
                Student.id.in_(unique_ids),
            )
        )
        students = list(students_result.scalars().all())

        found_ids = {student.id for student in students}
        missing_ids = [sid for sid in unique_ids if sid not in found_ids]
        if missing_ids:
            raise ValidationException(
                f"Some students were not found in this school: {', '.join(str(sid) for sid in missing_ids)}"
            )
        await self._ensure_students_are_active(students)
        await self._ensure_students_are_enrolled(students, school_id)

        for student in students:
            student.parent_id = parent.id

        await self.db.flush()
        await self.db.commit()

        children = await self.parent_repo.get_children(parent_id, school_id)
        return parent.id, children

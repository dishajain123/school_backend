import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.teacher import TeacherRepository
from app.repositories.user import UserRepository
from app.schemas.teacher import TeacherCreate, TeacherUpdate
from app.models.teacher import Teacher
from app.core.security import hash_password
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ConflictException,
    ForbiddenException,
)
from app.core.dependencies import CurrentUser
from app.utils.enums import RoleEnum


class TeacherService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.teacher_repo = TeacherRepository(db)
        self.user_repo = UserRepository(db)

    async def create_teacher(
        self,
        payload: TeacherCreate,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Teacher:
        # Guard: email uniqueness
        existing_email = await self.user_repo.get_by_email(payload.user.email)
        if existing_email:
            raise ConflictException(detail="A user with this email already exists")

        # Guard: phone uniqueness
        existing_phone = await self.user_repo.get_by_phone(payload.user.phone)
        if existing_phone:
            raise ConflictException(detail="A user with this phone number already exists")

        # Guard: employee_code uniqueness
        existing_code = await self.teacher_repo.get_by_employee_code(payload.employee_code)
        if existing_code:
            raise ConflictException(detail="A teacher with this employee code already exists")

        # 1. Create users row (role=TEACHER)
        user = await self.user_repo.create(
            {
                "email": payload.user.email.lower().strip(),
                "phone": payload.user.phone,
                "hashed_password": hash_password(payload.user.password),
                "role": RoleEnum.TEACHER,
                "school_id": school_id,
                "is_active": True,
            }
        )

        # 2. Create teachers row linked to that user
        teacher = await self.teacher_repo.create(
            {
                "user_id": user.id,
                "school_id": school_id,
                "employee_code": payload.employee_code,
                "join_date": payload.join_date,
                "specialization": payload.specialization,
                "academic_year_id": payload.academic_year_id,
            }
        )

        await self.db.commit()

        # Reload with user eager-loaded
        return await self.teacher_repo.get_by_id(teacher.id, school_id)  # type: ignore[return-value]

    async def get_teacher(
        self,
        teacher_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Teacher:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        teacher = await self.teacher_repo.get_by_id(teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Teacher not found")

        # A TEACHER may only view their own profile
        if current_user.role == RoleEnum.TEACHER:
            if teacher.user_id != current_user.id:
                raise ForbiddenException(detail="Access denied")

        return teacher

    async def list_teachers(
        self,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        page: int,
        page_size: int,
    ) -> tuple[list[Teacher], int]:
        return await self.teacher_repo.list_by_school(
            school_id=school_id,
            academic_year_id=academic_year_id,
            page=page,
            page_size=page_size,
        )

    async def update_teacher(
        self,
        teacher_id: uuid.UUID,
        payload: TeacherUpdate,
        current_user: CurrentUser,
    ) -> Teacher:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("school_id is required")

        teacher = await self.teacher_repo.get_by_id(teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Teacher not found")

        update_data = payload.model_dump(exclude_unset=True)

        # Guard: employee_code uniqueness on update
        new_code = update_data.get("employee_code")
        if new_code and new_code != teacher.employee_code:
            existing_code = await self.teacher_repo.get_by_employee_code(new_code)
            if existing_code:
                raise ConflictException(
                    detail="A teacher with this employee code already exists"
                )

        updated = await self.teacher_repo.update(teacher, update_data)
        await self.db.commit()

        return await self.teacher_repo.get_by_id(teacher_id, school_id)  # type: ignore[return-value]
import math
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.models.identifier_counter import IdentifierCounter
from app.models.identifier_format_config import IdentifierFormatConfig
from app.models.parent import Parent
from app.models.school import School
from app.models.student import Student
from app.models.teacher import Teacher
from app.models.user import User
from app.schemas.role_profile import (
    IdentifierConfigCreate,
    IdentifierConfigResponse,
    IdentifierPreviewResponse,
    ParentProfileCreate,
    ParentProfileResponse,
    RoleProfileListResponse,
    StudentProfileCreate,
    StudentProfileResponse,
    TeacherProfileCreate,
    TeacherProfileResponse,
)
from app.services.identifier import IdentifierService
from app.utils.enums import IdentifierType, RoleEnum, UserStatus


class RoleProfileService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.identifier_service = IdentifierService(db)

    async def create_student_profile(
        self,
        data: StudentProfileCreate,
        current_user: CurrentUser,
    ) -> StudentProfileResponse:
        school_id, user = await self._get_target_user(
            user_id=data.user_id,
            expected_role=RoleEnum.STUDENT,
            current_user=current_user,
        )
        await self._ensure_no_existing_profile(data.user_id)

        parent = await self.db.execute(
            select(Parent).where(Parent.id == data.parent_id, Parent.school_id == school_id)
        )
        parent_obj = parent.scalar_one_or_none()
        if not parent_obj:
            raise ValidationException("Parent not found in the same school")

        payload = dict(user.submitted_data or {})
        if data.date_of_birth is not None:
            payload["date_of_birth"] = data.date_of_birth
        if data.admission_date is not None:
            payload["admission_date"] = data.admission_date

        student = await self.identifier_service.create_student_profile(
            user_id=data.user_id,
            school_id=school_id,
            parent_id=data.parent_id,
            submitted_data=payload,
            actor=current_user,
            custom_admission_number=data.custom_admission_number,
        )

        if data.standard_id is not None:
            student.standard_id = data.standard_id
        if data.section is not None:
            student.section = data.section

        await self.db.commit()
        await self.db.refresh(student)

        return StudentProfileResponse(
            student_id=student.id,
            user_id=student.user_id,
            admission_number=student.admission_number,
            is_identifier_custom=student.is_identifier_custom,
            identifier_issued_at=student.identifier_issued_at,
            date_of_birth=student.date_of_birth,
            admission_date=student.admission_date,
            standard_id=student.standard_id,
            section=student.section,
            profile_status="ACTIVE",
        )

    async def create_teacher_profile(
        self,
        data: TeacherProfileCreate,
        current_user: CurrentUser,
    ) -> TeacherProfileResponse:
        school_id, _ = await self._get_target_user(
            user_id=data.user_id,
            expected_role=RoleEnum.TEACHER,
            current_user=current_user,
        )
        await self._ensure_no_existing_profile(data.user_id)

        payload = {}
        if data.join_date is not None:
            payload["join_date"] = data.join_date
        if data.specialization is not None:
            payload["specialization"] = data.specialization

        teacher = await self.identifier_service.create_teacher_profile(
            user_id=data.user_id,
            school_id=school_id,
            submitted_data=payload,
            actor=current_user,
            custom_employee_id=data.custom_employee_id,
        )

        await self.db.commit()
        await self.db.refresh(teacher)

        return TeacherProfileResponse(
            teacher_id=teacher.id,
            user_id=teacher.user_id,
            employee_id=teacher.employee_code,
            is_identifier_custom=teacher.is_identifier_custom,
            identifier_issued_at=teacher.identifier_issued_at,
            join_date=teacher.join_date,
            specialization=teacher.specialization,
            profile_status="ACTIVE",
        )

    async def create_parent_profile(
        self,
        data: ParentProfileCreate,
        current_user: CurrentUser,
    ) -> ParentProfileResponse:
        school_id, _ = await self._get_target_user(
            user_id=data.user_id,
            expected_role=RoleEnum.PARENT,
            current_user=current_user,
        )
        await self._ensure_no_existing_profile(data.user_id)

        payload = {
            "occupation": data.occupation,
            "relation": data.relation,
        }

        parent = await self.identifier_service.create_parent_profile(
            user_id=data.user_id,
            school_id=school_id,
            submitted_data=payload,
            actor=current_user,
            custom_parent_code=data.custom_parent_code,
        )

        await self.db.commit()
        await self.db.refresh(parent)

        return ParentProfileResponse(
            parent_id=parent.id,
            user_id=parent.user_id,
            parent_code=parent.parent_code or "",
            is_identifier_custom=False,
            identifier_issued_at=parent.identifier_issued_at,
            occupation=parent.occupation,
            relation=parent.relation.value if hasattr(parent.relation, "value") else str(parent.relation),
            profile_status="ACTIVE",
        )

    async def list_profiles(
        self,
        school_id: Optional[uuid.UUID],
        role: Optional[str],
        page: int,
        page_size: int,
        search: Optional[str],
    ) -> RoleProfileListResponse:
        if school_id is None:
            raise ValidationException("school_id is required for listing role profiles")

        role_norm = (role or "STUDENT").upper()
        if role_norm not in {"STUDENT", "TEACHER", "PARENT"}:
            raise ValidationException("role must be one of STUDENT, TEACHER, PARENT")

        if role_norm == "STUDENT":
            items, total = await self._list_student_profiles(school_id, page, page_size, search)
        elif role_norm == "TEACHER":
            items, total = await self._list_teacher_profiles(school_id, page, page_size, search)
        else:
            items, total = await self._list_parent_profiles(school_id, page, page_size, search)

        total_pages = math.ceil(total / page_size) if total else 1
        return RoleProfileListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def get_profile_by_user(
        self,
        user_id: uuid.UUID,
        school_id: Optional[uuid.UUID],
    ) -> dict[str, Any]:
        student_row = await self.db.execute(
            select(Student, User)
            .join(User, User.id == Student.user_id)
            .where(Student.user_id == user_id)
        )
        student = student_row.first()
        if student:
            s, u = student
            if school_id is not None and s.school_id != school_id:
                raise ForbiddenException("Profile is outside your school scope")
            return {
                "role": "STUDENT",
                "user_id": str(u.id),
                "full_name": u.full_name,
                "email": u.email,
                "phone": u.phone,
                "admission_number": s.admission_number,
                "is_identifier_custom": s.is_identifier_custom,
                "identifier_issued_at": s.identifier_issued_at,
                "date_of_birth": s.date_of_birth,
                "admission_date": s.admission_date,
                "standard_id": str(s.standard_id) if s.standard_id else None,
                "section": s.section,
            }

        teacher_row = await self.db.execute(
            select(Teacher, User)
            .join(User, User.id == Teacher.user_id)
            .where(Teacher.user_id == user_id)
        )
        teacher = teacher_row.first()
        if teacher:
            t, u = teacher
            if school_id is not None and t.school_id != school_id:
                raise ForbiddenException("Profile is outside your school scope")
            return {
                "role": "TEACHER",
                "user_id": str(u.id),
                "full_name": u.full_name,
                "email": u.email,
                "phone": u.phone,
                "employee_id": t.employee_code,
                "is_identifier_custom": t.is_identifier_custom,
                "identifier_issued_at": t.identifier_issued_at,
                "join_date": t.join_date,
                "specialization": t.specialization,
            }

        parent_row = await self.db.execute(
            select(Parent, User)
            .join(User, User.id == Parent.user_id)
            .where(Parent.user_id == user_id)
        )
        parent = parent_row.first()
        if parent:
            p, u = parent
            if school_id is not None and p.school_id != school_id:
                raise ForbiddenException("Profile is outside your school scope")
            return {
                "role": "PARENT",
                "user_id": str(u.id),
                "full_name": u.full_name,
                "email": u.email,
                "phone": u.phone,
                "parent_code": p.parent_code,
                "identifier_issued_at": p.identifier_issued_at,
                "occupation": p.occupation,
                "relation": p.relation.value if hasattr(p.relation, "value") else str(p.relation),
            }

        raise NotFoundException("Role profile")

    async def set_identifier_config(
        self,
        data: IdentifierConfigCreate,
        current_user: CurrentUser,
        school_id: Optional[uuid.UUID] = None,
    ) -> IdentifierConfigResponse:
        resolved_school_id = await self.resolve_school_scope(current_user, school_id)
        identifier_type = data.identifier_type

        if "{SEQ}" not in data.format_template:
            raise ValidationException("format_template must contain {SEQ}")

        result = await self.db.execute(
            select(IdentifierFormatConfig).where(
                IdentifierFormatConfig.school_id == resolved_school_id,
                IdentifierFormatConfig.identifier_type == identifier_type.value,
            )
        )
        config = result.scalar_one_or_none()
        if config is None:
            config = IdentifierFormatConfig(
                school_id=resolved_school_id,
                identifier_type=identifier_type.value,
            )
            self.db.add(config)

        if config.is_locked:
            raise ValidationException("Identifier format is locked after first identifier issuance")

        config.format_template = data.format_template.strip().upper()
        config.sequence_padding = data.sequence_padding
        config.reset_yearly = data.reset_yearly
        config.prefix = data.prefix
        config.configured_by_id = current_user.id

        await self.db.commit()
        await self.db.refresh(config)

        preview = await self.preview_next_identifier(resolved_school_id, identifier_type.value)
        return IdentifierConfigResponse(
            identifier_type=config.identifier_type,
            format_template=config.format_template,
            sequence_padding=config.sequence_padding,
            reset_yearly=config.reset_yearly,
            is_locked=config.is_locked,
            prefix=config.prefix,
            preview_next=preview.next_identifier,
            warning="Format is locked" if config.is_locked else None,
        )

    async def get_identifier_configs(
        self,
        school_id: Optional[uuid.UUID],
    ) -> list[IdentifierConfigResponse]:
        if school_id is None:
            raise ValidationException("school_id is required for identifier configs")

        out: list[IdentifierConfigResponse] = []
        for identifier_type in IdentifierType:
            config = await self.identifier_service._get_or_create_config(school_id, identifier_type)
            preview = await self.preview_next_identifier(school_id, identifier_type.value)
            out.append(
                IdentifierConfigResponse(
                    identifier_type=config.identifier_type,
                    format_template=config.format_template,
                    sequence_padding=config.sequence_padding,
                    reset_yearly=config.reset_yearly,
                    is_locked=config.is_locked,
                    prefix=config.prefix,
                    preview_next=preview.next_identifier,
                    warning="Format is locked" if config.is_locked else None,
                )
            )

        await self.db.commit()
        return out

    async def preview_next_identifier(
        self,
        school_id: Optional[uuid.UUID],
        identifier_type: str,
    ) -> IdentifierPreviewResponse:
        if school_id is None:
            raise ValidationException("school_id is required for identifier preview")

        try:
            identifier_enum = IdentifierType(identifier_type)
        except ValueError as exc:
            raise ValidationException("Invalid identifier_type") from exc

        config = await self.identifier_service._get_or_create_config(school_id, identifier_enum)
        year = datetime.now().year
        year_tag = str(year) if config.reset_yearly else "ALL"

        counter_result = await self.db.execute(
            select(IdentifierCounter).where(
                IdentifierCounter.school_id == school_id,
                IdentifierCounter.identifier_type == identifier_enum.value,
                IdentifierCounter.year_tag == year_tag,
            )
        )
        counter = counter_result.scalar_one_or_none()
        current_counter = counter.last_number if counter else 0
        next_counter = current_counter + 1

        next_identifier = self.identifier_service._format_identifier(config, next_counter, year)

        return IdentifierPreviewResponse(
            identifier_type=identifier_enum.value,
            next_identifier=next_identifier,
            current_counter=current_counter,
            format_template=config.format_template,
            is_locked=config.is_locked,
        )

    async def _get_target_user(
        self,
        user_id: uuid.UUID,
        expected_role: RoleEnum,
        current_user: CurrentUser,
    ) -> tuple[uuid.UUID, User]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException("User")

        if user.role != expected_role:
            raise ValidationException(f"User role mismatch. Expected {expected_role.value}")

        if current_user.role != RoleEnum.SUPERADMIN:
            if current_user.school_id is None or user.school_id != current_user.school_id:
                raise ForbiddenException("User is outside your school scope")

        if user.school_id is None:
            raise ValidationException("Target user has no school assigned")

        if user.status != UserStatus.ACTIVE or not user.is_active:
            raise ValidationException("Role profile can only be created for ACTIVE users")

        return user.school_id, user

    async def _ensure_no_existing_profile(self, user_id: uuid.UUID) -> None:
        checks = [
            select(Student.id).where(Student.user_id == user_id),
            select(Teacher.id).where(Teacher.user_id == user_id),
            select(Parent.id).where(Parent.user_id == user_id),
        ]
        for stmt in checks:
            result = await self.db.execute(stmt)
            if result.scalar_one_or_none() is not None:
                raise ValidationException("Role profile already exists for this user")

    async def resolve_school_scope(
        self,
        current_user: CurrentUser,
        school_id: Optional[uuid.UUID],
    ) -> uuid.UUID:
        if current_user.role == RoleEnum.SUPERADMIN:
            if school_id is not None:
                return school_id
            if current_user.school_id is not None:
                return current_user.school_id
            schools = (
                await self.db.execute(
                    select(School.id).order_by(School.created_at.asc()).limit(2)
                )
            ).scalars().all()
            if not schools:
                raise ValidationException("No schools found. Create a school first.")
            if len(schools) > 1:
                raise ValidationException(
                    "school_id is required for superadmin when multiple schools exist"
                )
            return schools[0]

        if current_user.school_id is None:
            raise ValidationException("Current user has no school scope")

        if school_id is not None and school_id != current_user.school_id:
            raise ForbiddenException("Cannot operate on another school")

        return current_user.school_id

    async def _list_student_profiles(
        self,
        school_id: uuid.UUID,
        page: int,
        page_size: int,
        search: Optional[str],
    ) -> tuple[list[dict[str, Any]], int]:
        filters = [Student.school_id == school_id]
        if search:
            q = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(User.full_name, "")).like(q),
                    func.lower(func.coalesce(User.email, "")).like(q),
                    func.lower(func.coalesce(User.phone, "")).like(q),
                    func.lower(func.coalesce(Student.admission_number, "")).like(q),
                )
            )

        stmt = (
            select(Student, User)
            .join(User, User.id == Student.user_id)
            .where(and_(*filters))
            .order_by(Student.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_stmt = (
            select(func.count(Student.id))
            .join(User, User.id == Student.user_id)
            .where(and_(*filters))
        )

        rows = (await self.db.execute(stmt)).all()
        total = (await self.db.execute(count_stmt)).scalar_one()
        items = [
            {
                "role": "STUDENT",
                "user_id": str(user.id),
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "identifier": student.admission_number,
                "admission_number": student.admission_number,
                "is_identifier_custom": student.is_identifier_custom,
                "identifier_issued_at": student.identifier_issued_at,
                "standard_id": str(student.standard_id) if student.standard_id else None,
                "section": student.section,
                "created_at": student.created_at,
            }
            for student, user in rows
        ]
        return items, total

    async def _list_teacher_profiles(
        self,
        school_id: uuid.UUID,
        page: int,
        page_size: int,
        search: Optional[str],
    ) -> tuple[list[dict[str, Any]], int]:
        filters = [Teacher.school_id == school_id]
        if search:
            q = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(User.full_name, "")).like(q),
                    func.lower(func.coalesce(User.email, "")).like(q),
                    func.lower(func.coalesce(User.phone, "")).like(q),
                    func.lower(func.coalesce(Teacher.employee_code, "")).like(q),
                )
            )

        stmt = (
            select(Teacher, User)
            .join(User, User.id == Teacher.user_id)
            .where(and_(*filters))
            .order_by(Teacher.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_stmt = (
            select(func.count(Teacher.id))
            .join(User, User.id == Teacher.user_id)
            .where(and_(*filters))
        )

        rows = (await self.db.execute(stmt)).all()
        total = (await self.db.execute(count_stmt)).scalar_one()
        items = [
            {
                "role": "TEACHER",
                "user_id": str(user.id),
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "identifier": teacher.employee_code,
                "employee_id": teacher.employee_code,
                "is_identifier_custom": teacher.is_identifier_custom,
                "identifier_issued_at": teacher.identifier_issued_at,
                "specialization": teacher.specialization,
                "join_date": teacher.join_date,
                "created_at": teacher.created_at,
            }
            for teacher, user in rows
        ]
        return items, total

    async def _list_parent_profiles(
        self,
        school_id: uuid.UUID,
        page: int,
        page_size: int,
        search: Optional[str],
    ) -> tuple[list[dict[str, Any]], int]:
        filters = [Parent.school_id == school_id]
        if search:
            q = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(User.full_name, "")).like(q),
                    func.lower(func.coalesce(User.email, "")).like(q),
                    func.lower(func.coalesce(User.phone, "")).like(q),
                    func.lower(func.coalesce(Parent.parent_code, "")).like(q),
                )
            )

        stmt = (
            select(Parent, User)
            .join(User, User.id == Parent.user_id)
            .where(and_(*filters))
            .order_by(Parent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_stmt = (
            select(func.count(Parent.id))
            .join(User, User.id == Parent.user_id)
            .where(and_(*filters))
        )

        rows = (await self.db.execute(stmt)).all()
        total = (await self.db.execute(count_stmt)).scalar_one()
        items = [
            {
                "role": "PARENT",
                "user_id": str(user.id),
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "identifier": parent.parent_code,
                "parent_code": parent.parent_code,
                "occupation": parent.occupation,
                "relation": parent.relation.value if hasattr(parent.relation, "value") else str(parent.relation),
                "identifier_issued_at": parent.identifier_issued_at,
                "created_at": parent.created_at,
            }
            for parent, user in rows
        ]
        return items, total

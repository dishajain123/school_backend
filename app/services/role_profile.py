import math
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.models.parent import Parent
from app.models.student import Student
from app.models.student_year_mapping import StudentYearMapping
from app.models.teacher import Teacher
from app.models.user import User
from app.models.identifier_counter import IdentifierCounter
from app.models.identifier_format_config import IdentifierFormatConfig
from app.schemas.role_profile import (
    IdentifierConfigResponse,
    IdentifierConfigUpsertRequest,
    ParentProfileCreate,
    ParentProfileResponse,
    RoleProfileListResponse,
    StudentProfileCreate,
    StudentProfileResponse,
    TeacherProfileCreate,
    TeacherProfileResponse,
)
from app.services.identifier import DEFAULT_FORMATS, IdentifierService
from app.utils.enums import EnrollmentStatus, IdentifierType, RoleEnum, UserStatus


class RoleProfileService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.identifier_service = IdentifierService(db)

    @staticmethod
    def _display_name(user: User) -> str:
        if user.full_name and user.full_name.strip():
            return user.full_name.strip()
        if user.email and "@" in user.email:
            local = user.email.split("@", 1)[0]
            cleaned = re.sub(r"[\._\-]+", " ", local).strip()
            if cleaned:
                return " ".join(part.capitalize() for part in cleaned.split())
        if user.phone and user.phone.strip():
            return user.phone.strip()
        return "Unknown"

    @staticmethod
    def _normalize_admission_values(submitted_data: Optional[dict[str, Any]]) -> list[str]:
        if not submitted_data:
            return []
        values: list[str] = []
        first = (
            submitted_data.get("student_admission_number")
            or submitted_data.get("admission_number")
            or submitted_data.get("child_admission_number")
        )
        if isinstance(first, str) and first.strip():
            values.append(first.strip())
        extra = submitted_data.get("child_admission_numbers")
        if isinstance(extra, list):
            values.extend([str(v).strip() for v in extra if str(v).strip()])
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.upper()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped

    async def _auto_link_parent_children_from_submission(
        self,
        *,
        parent: Parent,
        user: User,
        school_id: uuid.UUID,
    ) -> None:
        admissions = self._normalize_admission_values(
            user.submitted_data if isinstance(user.submitted_data, dict) else None
        )
        if not admissions:
            return
        admissions_upper = [a.strip().upper() for a in admissions if a.strip()]
        if not admissions_upper:
            return
        rows = await self.db.execute(
            select(Student)
            .where(
                Student.school_id == school_id,
                func.upper(func.trim(Student.admission_number)).in_(admissions_upper),
            )
        )
        students = list(rows.scalars().all())
        if not students:
            return
        student_ids = [s.id for s in students]
        active_rows = await self.db.execute(
            select(StudentYearMapping.student_id)
            .where(
                StudentYearMapping.school_id == school_id,
                StudentYearMapping.student_id.in_(student_ids),
                StudentYearMapping.status == EnrollmentStatus.ACTIVE,
            )
            .group_by(StudentYearMapping.student_id)
        )
        active_student_ids = set(active_rows.scalars().all())
        if not active_student_ids:
            return
        for student in students:
            if student.id in active_student_ids:
                student.parent_id = parent.id
        await self.db.flush()

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
        school_id, user = await self._get_target_user(
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

        # Auto-link children from parent registration submission (admission numbers),
        # so admin only verifies and proceeds with enrollment.
        await self._auto_link_parent_children_from_submission(
            parent=parent,
            user=user,
            school_id=school_id,
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
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
    ) -> RoleProfileListResponse:
        if school_id is None:
            raise ValidationException("school_id is required for listing role profiles")

        role_norm = (role or "STUDENT").upper()
        if role_norm not in {"STUDENT", "TEACHER", "PARENT", "PRINCIPAL", "TRUSTEE"}:
            raise ValidationException(
                "role must be one of STUDENT, TEACHER, PARENT, PRINCIPAL, TRUSTEE"
            )

        if role_norm == "STUDENT":
            items, total = await self._list_student_profiles(
                school_id=school_id,
                page=page,
                page_size=page_size,
                search=search,
                academic_year_id=academic_year_id,
                standard_id=standard_id,
                section=section,
            )
        elif role_norm == "TEACHER":
            items, total = await self._list_teacher_profiles(
                school_id=school_id,
                page=page,
                page_size=page_size,
                search=search,
                academic_year_id=academic_year_id,
            )
        elif role_norm == "PRINCIPAL":
            items, total = await self._list_user_role_profiles(
                school_id=school_id,
                role=RoleEnum.PRINCIPAL,
                page=page,
                page_size=page_size,
                search=search,
            )
        elif role_norm == "TRUSTEE":
            items, total = await self._list_user_role_profiles(
                school_id=school_id,
                role=RoleEnum.TRUSTEE,
                page=page,
                page_size=page_size,
                search=search,
            )
        else:
            items, total = await self._list_parent_profiles(
                school_id=school_id,
                page=page,
                page_size=page_size,
                search=search,
                academic_year_id=academic_year_id,
            )

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
                "student_id": str(s.id),
                "user_id": str(u.id),
                "full_name": self._display_name(u),
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
                "teacher_id": str(t.id),
                "user_id": str(u.id),
                "full_name": self._display_name(u),
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
                "parent_id": str(p.id),
                "user_id": str(u.id),
                "full_name": self._display_name(u),
                "email": u.email,
                "phone": u.phone,
                "parent_code": p.parent_code or f"PAR-{str(u.id)[:8].upper()}",
                "identifier_issued_at": p.identifier_issued_at,
                "occupation": p.occupation,
                "relation": p.relation.value if hasattr(p.relation, "value") else str(p.relation),
            }

        raise NotFoundException("Role profile")

    async def list_identifier_configs(
        self,
        school_id: uuid.UUID,
    ) -> list[IdentifierConfigResponse]:
        rows = await self.db.execute(
            select(IdentifierFormatConfig).where(
                IdentifierFormatConfig.school_id == school_id
            )
        )
        existing = {r.identifier_type: r for r in rows.scalars().all()}
        items: list[IdentifierConfigResponse] = []

        for identifier_type in IdentifierType:
            cfg = existing.get(identifier_type.value)
            if cfg is None:
                defaults = DEFAULT_FORMATS[identifier_type]
                cfg = IdentifierFormatConfig(
                    school_id=school_id,
                    identifier_type=identifier_type.value,
                    format_template=defaults["format_template"],
                    sequence_padding=defaults["sequence_padding"],
                    reset_yearly=defaults["reset_yearly"],
                    is_locked=False,
                )
                self.db.add(cfg)
                await self.db.flush()

            preview = await self._preview_next_identifier(cfg)
            warning = (
                "Format is locked because identifiers were already issued."
                if cfg.is_locked
                else None
            )
            items.append(
                IdentifierConfigResponse(
                    identifier_type=cfg.identifier_type,
                    format_template=cfg.format_template,
                    sequence_padding=cfg.sequence_padding,
                    reset_yearly=cfg.reset_yearly,
                    is_locked=cfg.is_locked,
                    prefix=cfg.prefix,
                    preview_next=preview,
                    warning=warning,
                )
            )

        await self.db.commit()
        return items

    async def upsert_identifier_config(
        self,
        school_id: uuid.UUID,
        payload: IdentifierConfigUpsertRequest,
        actor: CurrentUser,
    ) -> IdentifierConfigResponse:
        try:
            id_type = IdentifierType(payload.identifier_type.upper())
        except Exception:
            raise ValidationException(
                "identifier_type must be one of ADMISSION_NUMBER, EMPLOYEE_ID, PARENT_CODE"
            )

        row = await self.db.execute(
            select(IdentifierFormatConfig).where(
                and_(
                    IdentifierFormatConfig.school_id == school_id,
                    IdentifierFormatConfig.identifier_type == id_type.value,
                )
            )
        )
        cfg = row.scalar_one_or_none()
        if cfg is None:
            cfg = IdentifierFormatConfig(
                school_id=school_id,
                identifier_type=id_type.value,
                format_template=payload.format_template.strip(),
                sequence_padding=payload.sequence_padding,
                reset_yearly=payload.reset_yearly,
                prefix=payload.prefix.strip() if payload.prefix else None,
                configured_by_id=actor.id,
            )
            self.db.add(cfg)
            await self.db.flush()
        else:
            new_prefix = payload.prefix.strip() if payload.prefix else None
            if cfg.is_locked and (
                cfg.format_template != payload.format_template.strip()
                or cfg.sequence_padding != payload.sequence_padding
                or cfg.reset_yearly != payload.reset_yearly
                or cfg.prefix != new_prefix
            ):
                raise ValidationException(
                    "Identifier format is locked and cannot be modified."
                )
            cfg.format_template = payload.format_template.strip()
            cfg.sequence_padding = payload.sequence_padding
            cfg.reset_yearly = payload.reset_yearly
            cfg.prefix = new_prefix
            cfg.configured_by_id = actor.id
            await self.db.flush()

        preview = await self._preview_next_identifier(cfg)
        warning = (
            "Format is locked because identifiers were already issued."
            if cfg.is_locked
            else None
        )
        await self.db.commit()
        return IdentifierConfigResponse(
            identifier_type=cfg.identifier_type,
            format_template=cfg.format_template,
            sequence_padding=cfg.sequence_padding,
            reset_yearly=cfg.reset_yearly,
            is_locked=cfg.is_locked,
            prefix=cfg.prefix,
            preview_next=preview,
            warning=warning,
        )

    async def _preview_next_identifier(self, cfg: IdentifierFormatConfig) -> str:
        year_tag = str(datetime.now().year) if cfg.reset_yearly else "ALL"
        row = await self.db.execute(
            select(IdentifierCounter.last_number).where(
                and_(
                    IdentifierCounter.school_id == cfg.school_id,
                    IdentifierCounter.identifier_type == cfg.identifier_type,
                    IdentifierCounter.year_tag == year_tag,
                )
            )
        )
        last_number = row.scalar_one_or_none() or 0
        seq_num = int(last_number) + 1

        year_val = datetime.now().year
        padded_seq = str(seq_num).zfill(cfg.sequence_padding)
        value = cfg.format_template.replace("{YEAR}", str(year_val))
        value = value.replace("{SEQ}", padded_seq)
        value = value.replace("{PREFIX}", cfg.prefix or "")
        return value


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


    async def _list_student_profiles(
        self,
        school_id: uuid.UUID,
        page: int,
        page_size: int,
        search: Optional[str],
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        filters = [Student.school_id == school_id]
        if academic_year_id is not None:
            filters.append(Student.academic_year_id == academic_year_id)
        if standard_id is not None:
            filters.append(Student.standard_id == standard_id)
        if section and section.strip():
            filters.append(func.upper(func.coalesce(Student.section, "")) == section.strip().upper())
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

        student_rows = (
            await self.db.execute(
                select(Student, User)
                .join(User, User.id == Student.user_id)
                .where(and_(*filters))
                .order_by(Student.created_at.desc())
            )
        ).all()

        student_ids = [student.id for student, _ in student_rows]
        enrolled_ids: set[uuid.UUID] = set()
        if student_ids:
            enrolled_rows = await self.db.execute(
                select(StudentYearMapping.student_id)
                .where(
                    StudentYearMapping.student_id.in_(student_ids),
                    StudentYearMapping.school_id == school_id,
                    StudentYearMapping.status == EnrollmentStatus.ACTIVE,
                )
                .group_by(StudentYearMapping.student_id)
            )
            enrolled_ids = set(enrolled_rows.scalars().all())

        items: list[dict[str, Any]] = [
            {
                "role": "STUDENT",
                "student_id": str(student.id),
                "user_id": str(user.id),
                "full_name": self._display_name(user),
                "email": user.email,
                "phone": user.phone,
                "identifier": student.admission_number,
                "admission_number": student.admission_number,
                "is_identifier_custom": student.is_identifier_custom,
                "identifier_issued_at": student.identifier_issued_at,
                "standard_id": str(student.standard_id) if student.standard_id else None,
                "section": student.section,
                "enrollment_completed": student.id in enrolled_ids,
                "created_at": student.created_at,
            }
            for student, user in student_rows
        ]

        # Include approved student users even when student profile is not yet created.
        # This avoids parent-child linking deadlocks in admin flows.
        if academic_year_id is None and standard_id is None and not (section and section.strip()):
            pending_filters = [
                User.school_id == school_id,
                User.role == RoleEnum.STUDENT,
                User.status == UserStatus.ACTIVE,
                User.is_active.is_(True),
                ~select(Student.id).where(Student.user_id == User.id).exists(),
            ]
            if search:
                q = f"%{search.strip().lower()}%"
                pending_filters.append(
                    or_(
                        func.lower(func.coalesce(User.full_name, "")).like(q),
                        func.lower(func.coalesce(User.email, "")).like(q),
                        func.lower(func.coalesce(User.phone, "")).like(q),
                    )
                )
            pending_rows = (
                await self.db.execute(
                    select(User)
                    .where(and_(*pending_filters))
                    .order_by(User.created_at.desc())
                )
            ).scalars().all()
            for user in pending_rows:
                submitted = dict(user.submitted_data or {})
                suggested_identifier = submitted.get("admission_number")
                items.append(
                    {
                        "role": "STUDENT",
                        "student_id": None,
                        "user_id": str(user.id),
                        "full_name": self._display_name(user),
                        "email": user.email,
                        "phone": user.phone,
                        "identifier": suggested_identifier,
                        "admission_number": suggested_identifier,
                        "is_identifier_custom": False,
                        "identifier_issued_at": None,
                        "standard_id": None,
                        "section": None,
                        "created_at": user.created_at,
                        "profile_created": False,
                    }
                )

        items.sort(key=lambda x: x.get("created_at") or datetime.min, reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return items[start:end], total

    async def _list_teacher_profiles(
        self,
        school_id: uuid.UUID,
        page: int,
        page_size: int,
        search: Optional[str],
        academic_year_id: Optional[uuid.UUID] = None,
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

        rows = (
            await self.db.execute(
                select(Teacher, User)
                .join(User, User.id == Teacher.user_id)
                .where(and_(*filters))
                .order_by(Teacher.created_at.desc())
            )
        ).all()
        items: list[dict[str, Any]] = [
            {
                "role": "TEACHER",
                "teacher_id": str(teacher.id),
                "user_id": str(user.id),
                "full_name": self._display_name(user),
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

        # Include approved teacher users even if profile is not yet created.
        pending_filters = [
            User.school_id == school_id,
            User.role == RoleEnum.TEACHER,
            User.status == UserStatus.ACTIVE,
            User.is_active.is_(True),
            ~select(Teacher.id).where(Teacher.user_id == User.id).exists(),
        ]
        if search:
            q = f"%{search.strip().lower()}%"
            pending_filters.append(
                or_(
                    func.lower(func.coalesce(User.full_name, "")).like(q),
                    func.lower(func.coalesce(User.email, "")).like(q),
                    func.lower(func.coalesce(User.phone, "")).like(q),
                )
            )
        pending_rows = (
            await self.db.execute(
                select(User).where(and_(*pending_filters)).order_by(User.created_at.desc())
            )
        ).scalars().all()
        for user in pending_rows:
            submitted = dict(user.submitted_data or {})
            suggested_identifier = (
                submitted.get("teacher_identifier")
                or submitted.get("employee_id")
                or submitted.get("identifier")
            )
            items.append(
                {
                    "role": "TEACHER",
                    "teacher_id": None,
                    "user_id": str(user.id),
                    "full_name": self._display_name(user),
                    "email": user.email,
                    "phone": user.phone,
                    "identifier": suggested_identifier,
                    "employee_id": suggested_identifier,
                    "is_identifier_custom": False,
                    "identifier_issued_at": None,
                    "specialization": None,
                    "join_date": None,
                    "created_at": user.created_at,
                    "profile_created": False,
                }
            )

        items.sort(key=lambda x: x.get("created_at") or datetime.min, reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return items[start:end], total

    async def _list_parent_profiles(
        self,
        school_id: uuid.UUID,
        page: int,
        page_size: int,
        search: Optional[str],
        academic_year_id: Optional[uuid.UUID] = None,
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

        stmt = select(Parent, User).join(User, User.id == Parent.user_id)
        count_stmt = select(func.count(Parent.id)).join(User, User.id == Parent.user_id)
        # Keep parent profiles visible immediately after approval/profile creation.
        # Do not gate profile visibility by child enrollment status.

        stmt = (
            stmt.where(and_(*filters))
            .order_by(Parent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_stmt = count_stmt.where(and_(*filters))

        rows = (await self.db.execute(stmt)).all()
        total = (await self.db.execute(count_stmt)).scalar_one()
        items = [
            {
                "role": "PARENT",
                "parent_id": str(parent.id),
                "user_id": str(user.id),
                "full_name": self._display_name(user),
                "email": user.email,
                "phone": user.phone,
                "identifier": parent.parent_code or f"PAR-{str(user.id)[:8].upper()}",
                "parent_code": parent.parent_code,
                "occupation": parent.occupation,
                "relation": parent.relation.value if hasattr(parent.relation, "value") else str(parent.relation),
                "identifier_issued_at": parent.identifier_issued_at,
                "created_at": parent.created_at,
            }
            for parent, user in rows
        ]
        return items, total

    async def _list_user_role_profiles(
        self,
        school_id: uuid.UUID,
        role: RoleEnum,
        page: int,
        page_size: int,
        search: Optional[str],
    ) -> tuple[list[dict[str, Any]], int]:
        filters = [
            User.school_id == school_id,
            User.role == role,
            User.status == UserStatus.ACTIVE,
            User.is_active.is_(True),
        ]
        if search:
            q = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(User.full_name, "")).like(q),
                    func.lower(func.coalesce(User.email, "")).like(q),
                    func.lower(func.coalesce(User.phone, "")).like(q),
                )
            )

        stmt = (
            select(User)
            .where(and_(*filters))
            .order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_stmt = select(func.count(User.id)).where(and_(*filters))

        users = (await self.db.execute(stmt)).scalars().all()
        total = (await self.db.execute(count_stmt)).scalar_one()
        role_value = role.value
        items = [
            {
                "role": role_value,
                "user_id": str(user.id),
                "full_name": self._display_name(user),
                "email": user.email,
                "phone": user.phone,
                "identifier": user.email or user.phone or str(user.id),
                "created_at": user.created_at,
                "profile_created": True,
                "enrollment_completed": True,
            }
            for user in users
        ]
        return items, total

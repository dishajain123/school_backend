import re
import uuid
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ValidationException
from app.models.academic_year import AcademicYear
from app.models.school import School
from app.models.student import Student
from app.models.teacher import Teacher
from app.core.security import hash_password
from app.models.user import User
from app.models.registration_request import RegistrationRequest
from app.repositories.user import UserRepository
from app.schemas.registration import RegistrationCreateRequest
from app.utils.enums import RegistrationSource, RoleEnum, UserStatus

_PHONE_PATTERN = re.compile(r"^\+?[0-9]{10,15}$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegistrationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        cleaned = re.sub(r"[\s\-()]+", "", phone or "")
        return cleaned

    @staticmethod
    def _normalize_identifier(value: str) -> str:
        return value.strip().upper()

    async def _assert_contact_uniqueness(self, email: Optional[str], phone: Optional[str]) -> None:
        if email:
            existing = await self.user_repo.get_by_email(email)
            if existing:
                raise ConflictException("A user with this email already exists")
        if phone:
            existing = await self.user_repo.get_by_phone(phone)
            if existing:
                raise ConflictException("A user with this phone number already exists")

    async def _resolve_school_id_from_payload(
        self, payload: RegistrationCreateRequest
    ) -> Optional[uuid.UUID]:
        if payload.school_id:
            return payload.school_id

        data = payload.submitted_data or {}

        # Student self-registration: infer by admission number.
        if payload.role == RoleEnum.STUDENT:
            admission = (
                data.get("admission_number")
                or data.get("student_admission_number")
                or data.get("child_admission_number")
            )
            if isinstance(admission, str) and admission.strip():
                normalized_adm = self._normalize_identifier(admission)
                rows = await self.db.execute(
                    select(Student.school_id).where(
                        func.upper(func.trim(Student.admission_number)) == normalized_adm
                    )
                )
                school_ids = list({sid for sid in rows.scalars().all() if sid is not None})
                if len(school_ids) == 1:
                    return school_ids[0]
                if len(school_ids) > 1:
                    raise ValidationException(
                        "Admission number matches multiple schools. Please contact admin."
                    )
                # Fallback: check existing student registration requests.
                reg_rows = await self.db.execute(
                    select(RegistrationRequest.school_id, RegistrationRequest.submitted_data).where(
                        RegistrationRequest.role_requested == RoleEnum.STUDENT
                    )
                )
                reg_school_ids: list[uuid.UUID] = []
                for school_id, submitted in reg_rows.all():
                    if not school_id or not isinstance(submitted, dict):
                        continue
                    reg_adm = submitted.get("admission_number")
                    if isinstance(reg_adm, str) and self._normalize_identifier(reg_adm) == normalized_adm:
                        reg_school_ids.append(school_id)
                reg_school_ids = list(set(reg_school_ids))
                if len(reg_school_ids) == 1:
                    return reg_school_ids[0]
                if len(reg_school_ids) > 1:
                    raise ValidationException(
                        "Admission number matches multiple schools. Please contact admin."
                    )

        # Parent self-registration: infer by one/multiple child admission numbers.
        if payload.role == RoleEnum.PARENT:
            admissions: list[str] = []
            first = (
                data.get("student_admission_number")
                or data.get("admission_number")
                or data.get("child_admission_number")
            )
            if isinstance(first, str) and first.strip():
                admissions.append(first.strip())
            extra = data.get("child_admission_numbers")
            if isinstance(extra, list):
                admissions.extend(
                    [str(v).strip() for v in extra if str(v).strip()]
                )
            # De-duplicate while preserving order
            admissions = [self._normalize_identifier(a) for a in admissions]
            admissions = list(dict.fromkeys(admissions))
            if not admissions:
                raise ValidationException(
                    "For parent registration, child admission number is required."
                )
            rows = await self.db.execute(
                select(Student.school_id, Student.admission_number).where(
                    func.upper(func.trim(Student.admission_number)).in_(admissions)
                )
            )
            school_ids = list({row[0] for row in rows.all() if row[0] is not None})
            if not school_ids:
                # Fallback: check student registration requests.
                reg_rows = await self.db.execute(
                    select(RegistrationRequest.school_id, RegistrationRequest.submitted_data).where(
                        RegistrationRequest.role_requested == RoleEnum.STUDENT
                    )
                )
                for school_id, submitted in reg_rows.all():
                    if not school_id or not isinstance(submitted, dict):
                        continue
                    reg_adm = submitted.get("admission_number")
                    if isinstance(reg_adm, str) and self._normalize_identifier(reg_adm) in admissions:
                        school_ids.append(school_id)
                school_ids = list(set(school_ids))
                if not school_ids:
                    raise ValidationException(
                        "None of the provided child admission numbers were found."
                    )
            if len(school_ids) > 1:
                raise ValidationException(
                    "Child admission numbers belong to different schools. Use one school only."
                )
            return school_ids[0]

        # Staff-side roles: infer by staff/teacher identifier where available.
        # Applies to TEACHER, PRINCIPAL, TRUSTEE for future-safe compatibility.
        if payload.role in (RoleEnum.TEACHER, RoleEnum.PRINCIPAL, RoleEnum.TRUSTEE):
            raw_identifier = (
                data.get("teacher_identifier")
                or data.get("staff_identifier")
                or data.get("employee_id")
                or data.get("employee_code")
            )
            if isinstance(raw_identifier, str) and raw_identifier.strip():
                normalized_staff_id = self._normalize_identifier(raw_identifier)
                # 1) Existing teacher profiles table
                rows = await self.db.execute(
                    select(Teacher.school_id).where(
                        func.upper(func.trim(Teacher.employee_id))
                        == normalized_staff_id
                    )
                )
                school_ids = list({sid for sid in rows.scalars().all() if sid is not None})
                if len(school_ids) == 1:
                    return school_ids[0]
                if len(school_ids) > 1:
                    raise ValidationException(
                        "Identifier matches multiple schools. Please contact admin."
                    )

                # 2) Existing staff registration requests (pending/old)
                reg_rows = await self.db.execute(
                    select(RegistrationRequest.school_id, RegistrationRequest.submitted_data).where(
                        RegistrationRequest.role_requested.in_(
                            [RoleEnum.TEACHER, RoleEnum.PRINCIPAL, RoleEnum.TRUSTEE]
                        )
                    )
                )
                reg_school_ids: list[uuid.UUID] = []
                for school_id, submitted in reg_rows.all():
                    if not school_id or not isinstance(submitted, dict):
                        continue
                    for key in (
                        "teacher_identifier",
                        "staff_identifier",
                        "employee_id",
                        "employee_code",
                    ):
                        val = submitted.get(key)
                        if isinstance(val, str) and self._normalize_identifier(val) == normalized_staff_id:
                            reg_school_ids.append(school_id)
                            break
                reg_school_ids = list(set(reg_school_ids))
                if len(reg_school_ids) == 1:
                    return reg_school_ids[0]
                if len(reg_school_ids) > 1:
                    raise ValidationException(
                        "Identifier matches multiple schools. Please contact admin."
                    )

        # Optional fallback: if exactly one active school exists, use it.
        active_rows = await self.db.execute(
            select(School.id).where(School.is_active.is_(True))
        )
        active_school_ids = active_rows.scalars().all()
        if len(active_school_ids) == 1:
            return active_school_ids[0]

        return None

    async def list_active_academic_years(
        self,
        school_id: Optional[uuid.UUID] = None,
    ) -> list[AcademicYear]:
        resolved_school_id = school_id
        if resolved_school_id is None:
            active_rows = await self.db.execute(
                select(School.id).where(School.is_active.is_(True))
            )
            active_school_ids = active_rows.scalars().all()
            if len(active_school_ids) == 1:
                resolved_school_id = active_school_ids[0]
            else:
                raise ValidationException(
                    "Unable to resolve school. Please provide school_id."
                )

        rows = await self.db.execute(
            select(AcademicYear)
            .where(
                and_(
                    AcademicYear.school_id == resolved_school_id,
                    AcademicYear.is_active.is_(True),
                )
            )
            .order_by(AcademicYear.start_date.desc())
        )
        return rows.scalars().all()

    async def create_registration(
        self,
        payload: RegistrationCreateRequest,
        source: RegistrationSource,
    ) -> User:
        normalized_email = str(payload.email).lower().strip() if payload.email else None
        normalized_phone = self._normalize_phone(payload.phone) if payload.phone else None

        if not normalized_email and not normalized_phone:
            raise ValidationException("Email or phone is required")

        if normalized_phone and not _PHONE_PATTERN.match(normalized_phone):
            raise ValidationException("Invalid phone number format")

        await self._assert_contact_uniqueness(normalized_email, normalized_phone)

        resolved_school_id = await self._resolve_school_id_from_payload(payload)
        if not resolved_school_id:
            raise ValidationException(
                "Unable to determine school from provided identifiers. Please contact admin."
            )

        submitted_data = dict(payload.submitted_data or {})
        if payload.role != RoleEnum.SUPERADMIN:
            academic_year_raw = submitted_data.get("academic_year_id")
            if not isinstance(academic_year_raw, str) or not academic_year_raw.strip():
                raise ValidationException(
                    "Academic year is required for registration."
                )
            try:
                academic_year_id = uuid.UUID(academic_year_raw.strip())
            except ValueError as exc:
                raise ValidationException("Invalid academic year.") from exc

            year_row = await self.db.execute(
                select(AcademicYear.id).where(
                    and_(
                        AcademicYear.id == academic_year_id,
                        AcademicYear.school_id == resolved_school_id,
                        AcademicYear.is_active.is_(True),
                    )
                )
            )
            if year_row.scalar_one_or_none() is None:
                raise ValidationException(
                    "Selected academic year is not active for this school."
                )
            submitted_data["academic_year_id"] = str(academic_year_id)

        user = await self.user_repo.create(
            {
                "full_name": payload.full_name.strip() if payload.full_name else None,
                "email": normalized_email,
                "phone": normalized_phone,
                "hashed_password": hash_password(payload.password),
                "role": payload.role,
                "school_id": resolved_school_id,
                "status": UserStatus.PENDING_APPROVAL,
                "registration_source": source,
                "is_active": False,
                "submitted_data": submitted_data,
            }
        )
        await self.db.flush()
        
        # Create immutable RegistrationRequest snapshot
        registration_request = RegistrationRequest(
            user_id=user.id,
            school_id=resolved_school_id,
            role_requested=payload.role,
            registration_source=source,
            full_name=user.full_name or "",
            email=normalized_email,
            phone=normalized_phone,
            submitted_data=submitted_data,
            has_duplicates=False,
            duplicate_details=None,
            data_complete=True,
            missing_fields=None,
            current_status=UserStatus.PENDING_APPROVAL,
        )
        self.db.add(registration_request)

        await self.db.refresh(user)
        return user

    async def validate_user_for_approval(self, user: User) -> tuple[list[dict], list[dict]]:
        issues: list[dict] = []
        duplicates: list[dict] = []

        if not user.full_name or not user.full_name.strip():
            issues.append({"field": "full_name", "message": "full_name is required"})

        if not user.school_id:
            issues.append({"field": "school_id", "message": "school_id is required"})

        if not user.email and not user.phone:
            issues.append({"field": "contact", "message": "email or phone is required"})
        elif user.email and not _EMAIL_PATTERN.match(user.email):
            issues.append({"field": "email", "message": "invalid email format"})

        if user.phone and not _PHONE_PATTERN.match(self._normalize_phone(user.phone)):
            issues.append({"field": "phone", "message": "invalid phone format"})

        if user.email:
            conflict_q = await self.db.execute(
                select(User.id)
                .where(and_(User.email == user.email, User.id != user.id))
                .limit(1)
            )
            conflict_id = conflict_q.scalar_one_or_none()
            if conflict_id:
                duplicates.append(
                    {
                        "type": "email",
                        "value": user.email,
                        "matched_user_id": str(conflict_id),
                    }
                )

        if user.phone:
            conflict_q = await self.db.execute(
                select(User.id)
                .where(and_(User.phone == user.phone, User.id != user.id))
                .limit(1)
            )
            conflict_id = conflict_q.scalar_one_or_none()
            if conflict_id:
                duplicates.append(
                    {
                        "type": "phone",
                        "value": user.phone,
                        "matched_user_id": str(conflict_id),
                    }
                )

        if user.full_name and user.school_id:
            full_name_norm = user.full_name.strip().lower()
            potential_q = await self.db.execute(
                select(User.id, User.full_name, User.role, User.email, User.phone)
                .where(
                    and_(
                        User.id != user.id,
                        User.school_id == user.school_id,
                        func.lower(func.trim(User.full_name)) == full_name_norm,
                        or_(
                            User.email.is_not(None),
                            User.phone.is_not(None),
                        ),
                    )
                )
                .limit(5)
            )
            for row in potential_q.all():
                duplicates.append(
                    {
                        "type": "basic_identity",
                        "matched_user_id": str(row.id),
                        "full_name": row.full_name,
                        "role": row.role.value if row.role else None,
                        "email": row.email,
                        "phone": row.phone,
                    }
                )

        return issues, duplicates

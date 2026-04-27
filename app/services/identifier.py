# app/services/identifier.py
"""
Identifier Generation Engine.
Central service responsible for:
  - Generating unique, sequential, formatted identifiers
  - Enforcing format rules per school
  - Preventing generation before approval
  - Supporting admin override with strict validation
  - Locking format after first identifier is issued
"""
import uuid
import re
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identifier_counter import IdentifierCounter
from app.models.identifier_format_config import IdentifierFormatConfig
from app.models.student import Student
from app.models.teacher import Teacher
from app.models.parent import Parent
from app.models.user import User
from app.utils.enums import IdentifierType, UserStatus, RoleEnum, AuditAction
from app.core.exceptions import (
    ValidationException, ForbiddenException, ConflictException, NotFoundException
)
from app.core.dependencies import CurrentUser


# ── Default formats per identifier type ──────────────────────────────────────
DEFAULT_FORMATS = {
    IdentifierType.ADMISSION_NUMBER: {
        "format_template": "{YEAR}/{SEQ}",
        "sequence_padding": 4,
        "reset_yearly": True,
    },
    IdentifierType.EMPLOYEE_ID: {
        "format_template": "EMP/{SEQ}",
        "sequence_padding": 4,
        "reset_yearly": False,
    },
    IdentifierType.PARENT_CODE: {
        "format_template": "PAR/{SEQ}",
        "sequence_padding": 4,
        "reset_yearly": False,
    },
}

# ── Regex: valid custom identifier override ───────────────────────────────────
CUSTOM_IDENTIFIER_PATTERN = re.compile(r'^[A-Z0-9][A-Z0-9\-/]{1,48}[A-Z0-9]$')


class IdentifierService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Generate next identifier for a role
    # ─────────────────────────────────────────────────────────────────────────
    async def generate(
        self,
        school_id: uuid.UUID,
        identifier_type: IdentifierType,
        year: Optional[int] = None,          # for student admission numbers
        custom_value: Optional[str] = None,  # admin override
        actor: Optional[CurrentUser] = None,
    ) -> str:
        """
        Main entry point. Returns a unique identifier string.
        If custom_value is provided:
          - Requires SUPER_ADMIN or ADMIN role
          - Validates format and uniqueness
          - Returns as-is (does NOT increment counter)
        """
        if custom_value:
            return await self._validate_and_use_custom(
                school_id, identifier_type, custom_value, actor
            )

        config = await self._get_or_create_config(school_id, identifier_type)
        year_tag = self._resolve_year_tag(config, year)
        next_num = await self._increment_counter(school_id, identifier_type, year_tag)
        identifier = self._format_identifier(config, next_num, year)

        # Lock format after first issuance
        if not config.is_locked:
            config.is_locked = True
            await self.db.flush()

        return identifier

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Create role profile after approval
    # ─────────────────────────────────────────────────────────────────────────
    async def create_student_profile(
        self,
        *,
        user_id: uuid.UUID,
        school_id: uuid.UUID,
        parent_id: uuid.UUID,
        submitted_data: dict,
        actor: CurrentUser,
        custom_admission_number: Optional[str] = None,
    ) -> Student:
        """Called immediately after user is APPROVED."""
        await self._assert_user_approved(user_id)

        now = datetime.now(timezone.utc)
        year = now.year
        admission_number = await self.generate(
            school_id=school_id,
            identifier_type=IdentifierType.ADMISSION_NUMBER,
            year=year,
            custom_value=custom_admission_number,
            actor=actor,
        )

        # Guard: no duplicate admission number in this school
        existing = await self.db.execute(
            select(Student).where(
                Student.school_id == school_id,
                Student.admission_number == admission_number,
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictException(
                f"Admission number '{admission_number}' is already in use."
            )

        student = Student(
            user_id=user_id,
            school_id=school_id,
            parent_id=parent_id,
            admission_number=admission_number,
            admission_date=submitted_data.get("admission_date") or now.date(),
            date_of_birth=submitted_data.get("date_of_birth"),
            is_identifier_custom=custom_admission_number is not None,
            identifier_issued_at=now,
        )
        self.db.add(student)
        await self.db.flush()
        return student

    async def create_teacher_profile(
        self,
        *,
        user_id: uuid.UUID,
        school_id: uuid.UUID,
        submitted_data: dict,
        actor: CurrentUser,
        custom_employee_id: Optional[str] = None,
    ) -> Teacher:
        await self._assert_user_approved(user_id)

        now = datetime.now(timezone.utc)
        employee_id = await self.generate(
            school_id=school_id,
            identifier_type=IdentifierType.EMPLOYEE_ID,
            custom_value=custom_employee_id,
            actor=actor,
        )

        existing = await self.db.execute(
            select(Teacher).where(
                Teacher.school_id == school_id,
                Teacher.employee_code == employee_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictException(f"Employee ID '{employee_id}' is already in use.")

        teacher = Teacher(
            user_id=user_id,
            school_id=school_id,
            employee_code=employee_id,
            join_date=submitted_data.get("join_date") or now.date(),
            specialization=submitted_data.get("specialization"),
            is_identifier_custom=custom_employee_id is not None,
            identifier_issued_at=now,
        )
        self.db.add(teacher)
        await self.db.flush()
        return teacher

    async def create_parent_profile(
        self,
        *,
        user_id: uuid.UUID,
        school_id: uuid.UUID,
        submitted_data: dict,
        actor: CurrentUser,
        custom_parent_code: Optional[str] = None,
    ) -> Parent:
        await self._assert_user_approved(user_id)

        now = datetime.now(timezone.utc)
        parent_code = await self.generate(
            school_id=school_id,
            identifier_type=IdentifierType.PARENT_CODE,
            custom_value=custom_parent_code,
            actor=actor,
        )

        existing = await self.db.execute(
            select(Parent).where(
                Parent.school_id == school_id,
                Parent.parent_code == parent_code,
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictException(f"Parent code '{parent_code}' is already in use.")

        parent = Parent(
            user_id=user_id,
            school_id=school_id,
            parent_code=parent_code,
            occupation=submitted_data.get("occupation"),
            relation=submitted_data.get("relation", "GUARDIAN"),
            identifier_issued_at=now,
        )
        self.db.add(parent)
        await self.db.flush()
        return parent

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────
    async def _assert_user_approved(self, user_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(User.status).where(User.id == user_id)
        )
        status = result.scalar_one_or_none()
        if status is None:
            raise NotFoundException("User not found.")
        if status != UserStatus.ACTIVE:
            raise ForbiddenException(
                "Role profile can only be created for ACTIVE (approved) users. "
                f"Current status: {status.value}"
            )

    async def _get_or_create_config(
        self, school_id: uuid.UUID, identifier_type: IdentifierType
    ) -> IdentifierFormatConfig:
        result = await self.db.execute(
            select(IdentifierFormatConfig).where(
                IdentifierFormatConfig.school_id == school_id,
                IdentifierFormatConfig.identifier_type == identifier_type.value,
            )
        )
        config = result.scalar_one_or_none()

        if config is None:
            # Auto-create from defaults — happens once per school per type
            defaults = DEFAULT_FORMATS[identifier_type]
            config = IdentifierFormatConfig(
                school_id=school_id,
                identifier_type=identifier_type.value,
                **defaults,
            )
            self.db.add(config)
            await self.db.flush()

        return config

    def _resolve_year_tag(self, config: IdentifierFormatConfig, year: Optional[int]) -> str:
        if config.reset_yearly:
            return str(year or datetime.now().year)
        return "ALL"

    async def _increment_counter(
        self,
        school_id: uuid.UUID,
        identifier_type: IdentifierType,
        year_tag: str,
    ) -> int:
        """
        Atomically increments and returns the next sequence number.
        Uses SELECT FOR UPDATE to prevent race conditions with concurrent requests.
        """
        from sqlalchemy import update

        result = await self.db.execute(
            select(IdentifierCounter)
            .where(
                IdentifierCounter.school_id == school_id,
                IdentifierCounter.identifier_type == identifier_type.value,
                IdentifierCounter.year_tag == year_tag,
            )
            .with_for_update()  # ROW-LEVEL LOCK — prevents race condition
        )
        counter = result.scalar_one_or_none()

        if counter is None:
            counter = IdentifierCounter(
                school_id=school_id,
                identifier_type=identifier_type.value,
                year_tag=year_tag,
                last_number=1,
            )
            self.db.add(counter)
            await self.db.flush()
            return 1
        else:
            counter.last_number += 1
            await self.db.flush()
            return counter.last_number

    def _format_identifier(
        self,
        config: IdentifierFormatConfig,
        seq_num: int,
        year: Optional[int],
    ) -> str:
        padded_seq = str(seq_num).zfill(config.sequence_padding)
        year_str = str(year or datetime.now().year)
        prefix = config.prefix or ""

        result = config.format_template
        result = result.replace("{YEAR}", year_str)
        result = result.replace("{SEQ}", padded_seq)
        result = result.replace("{PREFIX}", prefix)
        return result

    async def _validate_and_use_custom(
        self,
        school_id: uuid.UUID,
        identifier_type: IdentifierType,
        custom_value: str,
        actor: Optional[CurrentUser],
    ) -> str:
        """
        Admin override path. Validates format and checks uniqueness.
        Only ADMIN and SUPER_ADMIN can use custom identifiers.
        """
        # Permission
        if actor is None or actor.role not in [RoleEnum.ADMIN, RoleEnum.SUPERADMIN]:
            raise ForbiddenException(
                "Custom identifier override requires Admin or Super Admin role."
            )

        # Format validation
        cleaned = custom_value.strip().upper()
        if not CUSTOM_IDENTIFIER_PATTERN.match(cleaned):
            raise ValidationException(
                "Custom identifier must be 3-50 characters, "
                "uppercase alphanumeric with hyphens or slashes only, "
                "and cannot start or end with a separator."
            )

        # Uniqueness check across all identifiers of same type in school
        await self._check_custom_uniqueness(school_id, identifier_type, cleaned)

        return cleaned

    async def _check_custom_uniqueness(
        self,
        school_id: uuid.UUID,
        identifier_type: IdentifierType,
        value: str,
    ) -> None:
        if identifier_type == IdentifierType.ADMISSION_NUMBER:
            result = await self.db.execute(
                select(Student.id).where(
                    Student.school_id == school_id,
                    Student.admission_number == value,
                )
            )
        elif identifier_type == IdentifierType.EMPLOYEE_ID:
            result = await self.db.execute(
                select(Teacher.id).where(
                    Teacher.school_id == school_id,
                    Teacher.employee_code == value,
                )
            )
        else:  # PARENT_CODE
            result = await self.db.execute(
                select(Parent.id).where(
                    Parent.school_id == school_id,
                    Parent.parent_code == value,
                )
            )

        if result.scalar_one_or_none():
            raise ConflictException(
                f"The identifier '{value}' is already in use in this school."
            )
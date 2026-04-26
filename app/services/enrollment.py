# app/services/enrollment.py

import uuid
import math
from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import select, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.student_year_mapping import StudentYearMapping
from app.models.student import Student
from app.models.masters import Standard
from app.models.section import Section
from app.models.academic_year import AcademicYear
from app.models.user import User
from app.repositories.enrollment import EnrollmentRepository
from app.services.audit_log import AuditLogService
from app.schemas.student_year_mapping import (
    StudentYearMappingCreate, StudentYearMappingUpdate,
    StudentExitRequest, RollNumberAssignRequest,
    StudentYearMappingResponse, ClassRosterResponse,
)
from app.utils.enums import EnrollmentStatus, AuditAction, RoleEnum, UserStatus
from app.core.exceptions import (
    ConflictException, ValidationException,
    NotFoundException, ForbiddenException
)
from app.core.dependencies import CurrentUser


VALID_EXIT_STATUSES = {EnrollmentStatus.LEFT, EnrollmentStatus.TRANSFERRED}
VALID_EXIT_FROM     = {EnrollmentStatus.ACTIVE, EnrollmentStatus.HOLD}


class EnrollmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = EnrollmentRepository(db)
        self.audit = AuditLogService(db)

    # ────────────────────────────────────────────────────────────
    # CREATE MAPPING
    # ────────────────────────────────────────────────────────────
    async def create_mapping(
        self,
        data: StudentYearMappingCreate,
        actor: CurrentUser,
    ) -> StudentYearMapping:
        school_id = actor.school_id

        # 1. Load and validate student
        student = await self._load_student(data.student_id, school_id)
        await self._ensure_student_is_approved(student, school_id)

        # 2. Duplicate check: one mapping per student per year
        existing = await self.repo.get_by_student_year(data.student_id, data.academic_year_id)
        if existing:
            raise ConflictException(
                f"Student already has an enrollment mapping for this academic year. "
                f"Current status: {existing.status.value}"
            )

        # 3. Validate standard belongs to year + school
        std = await self._load_standard(data.standard_id, data.academic_year_id, school_id)

        # 4. Validate section (if provided)
        section_name = None
        if data.section_id:
            section = await self._load_section(
                data.section_id, data.standard_id, data.academic_year_id
            )
            section_name = section.name

            # 5. Capacity check (non-blocking — warning only)
            enrolled_count = await self.repo.count_active_in_section(
                data.section_id, data.academic_year_id
            )
            if section.capacity and enrolled_count >= section.capacity:
                # Not a hard block — admin can override
                pass  # Future: return warning in response

        # 6. Create mapping
        mapping = StudentYearMapping(
            student_id=data.student_id,
            school_id=school_id,
            academic_year_id=data.academic_year_id,
            standard_id=data.standard_id,
            section_id=data.section_id,
            section_name=section_name,
            roll_number=data.roll_number,
            status=EnrollmentStatus.ACTIVE,
            joined_on=data.joined_on or date.today(),
            created_by_id=actor.id,
            last_modified_by_id=actor.id,
        )
        self.db.add(mapping)
        await self.db.flush()

        # 7. Sync Student flat fields (denormalized cache)
        await self._sync_student_flat_fields(student, mapping)

        # 8. Audit
        await self.audit.log(
            action=AuditAction.STUDENT_ENROLLED,
            actor_id=actor.id,
            target_user_id=student.user_id,
            entity_type="StudentYearMapping",
            entity_id=str(mapping.id),
            description=(
                f"{actor.full_name} enrolled student '{student.admission_number}' "
                f"into {std.name} Section {section_name or 'N/A'} "
                f"for academic year {data.academic_year_id}."
            ),
        )

        await self.db.commit()
        await self.db.refresh(mapping)
        return mapping

    # ────────────────────────────────────────────────────────────
    # UPDATE MAPPING
    # ────────────────────────────────────────────────────────────
    async def update_mapping(
        self,
        mapping_id: uuid.UUID,
        data: StudentYearMappingUpdate,
        actor: CurrentUser,
    ) -> StudentYearMapping:
        mapping = await self.repo.get_by_id(mapping_id)
        if not mapping or mapping.school_id != actor.school_id:
            raise NotFoundException("Enrollment mapping not found.")

        # Support class/section/roll updates. Use dedicated endpoint for exits.
        if data.standard_id:
            await self._load_standard(
                data.standard_id, mapping.academic_year_id, actor.school_id
            )
            mapping.standard_id = data.standard_id

        if data.section_id:
            section = await self._load_section(
                data.section_id,
                data.standard_id or mapping.standard_id,
                mapping.academic_year_id,
            )
            mapping.section_id = data.section_id
            mapping.section_name = section.name

        if data.roll_number is not None:
            mapping.roll_number = data.roll_number
        if data.joined_on is not None:
            mapping.joined_on = data.joined_on

        mapping.last_modified_by_id = actor.id
        await self.db.flush()

        student = await self.db.get(Student, mapping.student_id)
        if student and student.academic_year_id == mapping.academic_year_id:
            await self._sync_student_flat_fields(student, mapping)

        await self.db.commit()
        await self.db.refresh(mapping)
        return mapping

    async def get_mapping(
        self,
        mapping_id: uuid.UUID,
        actor: CurrentUser,
    ) -> StudentYearMapping:
        mapping = await self.repo.get_by_id(mapping_id)
        if not mapping or mapping.school_id != actor.school_id:
            raise NotFoundException("Enrollment mapping not found.")
        return mapping

    # ────────────────────────────────────────────────────────────
    # EXIT STUDENT
    # ────────────────────────────────────────────────────────────
    async def exit_student(
        self,
        mapping_id: uuid.UUID,
        data: StudentExitRequest,
        actor: CurrentUser,
    ) -> StudentYearMapping:
        mapping = await self.repo.get_by_id(mapping_id)
        if not mapping or mapping.school_id != actor.school_id:
            raise NotFoundException("Enrollment mapping not found.")

        if data.status not in VALID_EXIT_STATUSES:
            raise ValidationException(
                f"Exit status must be LEFT or TRANSFERRED. Got: {data.status.value}"
            )
        if mapping.status not in VALID_EXIT_FROM:
            raise ValidationException(
                f"Cannot exit a student with status: {mapping.status.value}. "
                f"Must be ACTIVE or HOLD."
            )
        if data.left_on > date.today():
            raise ValidationException("Exit date cannot be in the future.")

        before = {"status": mapping.status.value}

        mapping.status = data.status
        mapping.left_on = data.left_on
        mapping.exit_reason = data.exit_reason
        mapping.last_modified_by_id = actor.id
        await self.db.flush()

        await self.audit.log(
            action=AuditAction.STUDENT_EXITED,
            actor_id=actor.id,
            target_user_id=mapping.student.user_id if mapping.student else None,
            entity_type="StudentYearMapping",
            entity_id=str(mapping_id),
            description=(
                f"{actor.full_name} marked student as {data.status.value}. "
                f"Reason: {data.exit_reason}"
            ),
            before_state=before,
            after_state={"status": data.status.value, "left_on": str(data.left_on)},
        )
        await self.db.commit()
        return mapping

    # ────────────────────────────────────────────────────────────
    # CLASS ROSTER
    # ────────────────────────────────────────────────────────────
    async def get_class_roster(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        section_id: Optional[uuid.UUID],
        academic_year_id: uuid.UUID,
    ) -> ClassRosterResponse:
        mappings = await self.repo.list_for_roster(
            school_id=school_id,
            standard_id=standard_id,
            section_id=section_id,
            academic_year_id=academic_year_id,
        )

        # Load related names
        year_result = await self.db.execute(
            select(AcademicYear).where(AcademicYear.id == academic_year_id)
        )
        year = year_result.scalar_one_or_none()

        std_result = await self.db.execute(
            select(Standard).where(Standard.id == standard_id)
        )
        std = std_result.scalar_one_or_none()

        section_name = None
        if section_id:
            sec_result = await self.db.execute(
                select(Section).where(Section.id == section_id)
            )
            sec = sec_result.scalar_one_or_none()
            section_name = sec.name if sec else None

        active_count = sum(1 for m in mappings if m.status == EnrollmentStatus.ACTIVE)
        left_count = sum(1 for m in mappings if m.status in {
            EnrollmentStatus.LEFT, EnrollmentStatus.TRANSFERRED
        })

        return ClassRosterResponse(
            academic_year_id=academic_year_id,
            academic_year_name=year.name if year else "-",
            standard_id=standard_id,
            standard_name=std.name if std else "-",
            section_name=section_name,
            total_enrolled=len(mappings),
            active_count=active_count,
            left_count=left_count,
            mappings=[self._to_response(m) for m in mappings],
        )

    # ────────────────────────────────────────────────────────────
    # ROLL NUMBER ASSIGNMENT
    # ────────────────────────────────────────────────────────────
    async def assign_roll_numbers(
        self,
        data: RollNumberAssignRequest,
        actor: CurrentUser,
    ) -> dict:
        mappings = await self.repo.list_for_roster(
            school_id=actor.school_id,
            standard_id=data.standard_id,
            section_id=data.section_id,
            academic_year_id=data.academic_year_id,
            status_filter=EnrollmentStatus.ACTIVE,
        )

        if not mappings:
            raise ValidationException("No active students found in this class/section.")

        if data.policy == "MANUAL":
            return await self._assign_roll_manual(mappings, data.manual_assignments or [])

        # AUTO_SEQ: sort by joined_on then student id
        if data.policy == "AUTO_SEQ":
            sorted_mappings = sorted(
                mappings,
                key=lambda m: (m.joined_on or date.min, str(m.student_id)),
            )
        else:  # AUTO_ALPHA — default Indian school standard
            sorted_mappings = sorted(
                mappings,
                key=lambda m: (
                    (m.student.user.full_name or "").lower()
                    if m.student and m.student.user else ""
                ),
            )

        pad_width = 3 if len(sorted_mappings) > 99 else 2
        assignments = []
        for idx, mapping in enumerate(sorted_mappings, start=1):
            roll = str(idx).zfill(pad_width)
            mapping.roll_number = roll
            assignments.append({
                "student_name": (
                    mapping.student.user.full_name
                    if mapping.student and mapping.student.user else "-"
                ),
                "roll_number": roll,
            })

        await self.db.flush()

        # Sync to Student flat fields
        for mapping in sorted_mappings:
            student = await self.db.get(Student, mapping.student_id)
            if student and student.academic_year_id == mapping.academic_year_id:
                student.roll_number = mapping.roll_number

        await self.db.commit()
        return {
            "assigned_count": len(assignments),
            "policy": data.policy,
            "assignments": assignments,
        }

    # ────────────────────────────────────────────────────────────
    # HELPERS
    # ────────────────────────────────────────────────────────────
    async def _load_student(self, student_id: uuid.UUID, school_id: uuid.UUID) -> Student:
        result = await self.db.execute(
            select(Student).where(
                Student.id == student_id,
                Student.school_id == school_id,
            )
        )
        student = result.scalar_one_or_none()
        if not student:
            raise NotFoundException("Student not found in this school.")
        return student

    async def _load_standard(
        self, standard_id: uuid.UUID, academic_year_id: uuid.UUID, school_id: uuid.UUID
    ) -> Standard:
        result = await self.db.execute(
            select(Standard).where(
                Standard.id == standard_id,
                Standard.school_id == school_id,
                Standard.academic_year_id == academic_year_id,
            )
        )
        std = result.scalar_one_or_none()
        if not std:
            raise NotFoundException("Standard not found for this academic year.")
        return std

    async def _load_section(
        self, section_id: uuid.UUID, standard_id: uuid.UUID, academic_year_id: uuid.UUID
    ) -> Section:
        result = await self.db.execute(
            select(Section).where(
                Section.id == section_id,
                Section.standard_id == standard_id,
                Section.academic_year_id == academic_year_id,
                Section.is_active == True,
            )
        )
        section = result.scalar_one_or_none()
        if not section:
            raise NotFoundException("Section not found or inactive for this class.")
        return section

    async def _ensure_student_is_approved(
        self, student: Student, school_id: uuid.UUID
    ) -> None:
        if not student.user_id:
            raise ValidationException("Student must be linked to a user before mapping.")

        result = await self.db.execute(
            select(User).where(
                User.id == student.user_id,
                User.school_id == school_id,
            )
        )
        user = result.scalar_one_or_none()
        if not user:
            raise ValidationException("Linked student user account not found.")
        if user.status != UserStatus.ACTIVE or not user.is_active:
            raise ForbiddenException(
                "Student mapping is allowed only for approved active users."
            )

    async def _sync_student_flat_fields(
        self, student: Student, mapping: StudentYearMapping
    ) -> None:
        """Keep Student denormalized cache in sync with active mapping."""
        student.standard_id = mapping.standard_id
        student.academic_year_id = mapping.academic_year_id
        student.section = mapping.section_name
        student.roll_number = mapping.roll_number
        await self.db.flush()

    def _to_response(self, m: StudentYearMapping) -> StudentYearMappingResponse:
        return StudentYearMappingResponse(
            id=m.id,
            student_id=m.student_id,
            school_id=m.school_id,
            academic_year_id=m.academic_year_id,
            standard_id=m.standard_id,
            section_id=m.section_id,
            section_name=m.section_name,
            roll_number=m.roll_number,
            status=m.status,
            joined_on=m.joined_on,
            left_on=m.left_on,
            exit_reason=m.exit_reason,
            student_name=(
                m.student.user.full_name
                if m.student and m.student.user else None
            ),
            admission_number=m.student.admission_number if m.student else None,
            standard_name=m.standard.name if m.standard else None,
            academic_year_name=m.academic_year.name if m.academic_year else None,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    async def _assign_roll_manual(self, mappings, assignments: list[dict]) -> dict:
        mapping_map = {str(m.student_id): m for m in mappings}
        used_rolls = set()
        conflicts = []
        result_assignments = []

        for item in assignments:
            sid = str(item.get("student_id"))
            roll = str(item.get("roll_number", "")).strip()
            if roll in used_rolls:
                conflicts.append({"student_id": sid, "roll_number": roll})
                continue
            if sid in mapping_map:
                mapping_map[sid].roll_number = roll
                used_rolls.add(roll)
                result_assignments.append({
                    "student_id": sid,
                    "roll_number": roll,
                })

        if conflicts:
            raise ConflictException(
                f"Duplicate roll numbers detected: {conflicts}"
            )

        await self.db.flush()
        await self.db.commit()
        return {
            "assigned_count": len(result_assignments),
            "policy": "MANUAL",
            "assignments": result_assignments,
        }

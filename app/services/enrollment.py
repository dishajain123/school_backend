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
from app.models.teacher import Teacher
from app.models.parent import Parent
from app.models.teacher_class_subject import TeacherClassSubject
from app.repositories.enrollment import EnrollmentRepository
from app.services.audit_log import AuditLogService
from app.services.academic_year import get_active_year
from app.schemas.enrollment import (
    EnrollmentMappingCreate,
    EnrollmentMappingUpdate,
    EnrollmentExitRequest,
    EnrollmentCompleteRequest,
    SectionTransferRequest,
    RollNumberAssignRequest,
    EnrollmentMappingResponse,
    ClassRosterResponse,
    StudentAcademicHistoryResponse,
)
from app.utils.enums import EnrollmentStatus, AuditAction, RoleEnum, UserStatus
from app.core.exceptions import (
    ConflictException, ValidationException,
    NotFoundException, ForbiddenException
)
from app.core.dependencies import CurrentUser


VALID_EXIT_STATUSES = {EnrollmentStatus.LEFT, EnrollmentStatus.TRANSFERRED}
VALID_EXIT_FROM     = {EnrollmentStatus.ACTIVE, EnrollmentStatus.HOLD}
VALID_UPDATE_FROM   = {EnrollmentStatus.ACTIVE, EnrollmentStatus.HOLD}


class EnrollmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = EnrollmentRepository(db)
        self.audit = AuditLogService(db)

    async def list_onboarding_queue(
        self,
        school_id: uuid.UUID,
        role: Optional[RoleEnum] = None,
        pending_only: bool = False,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        if academic_year_id is not None:
            active_year = await self._load_academic_year(academic_year_id, school_id)
        else:
            active_year = await get_active_year(school_id, self.db)
        filters = [
            User.school_id == school_id,
            User.status == UserStatus.ACTIVE,
        ]
        if role is not None:
            filters.append(User.role == role)

        rows = await self.db.execute(
            select(User).where(and_(*filters)).order_by(User.created_at.desc())
        )
        users = list(rows.scalars().all())

        items: list[dict] = []
        for u in users:
            profile_created = False
            enrollment_completed = False
            pending_reason: Optional[str] = None
            suggested_identifier: Optional[str] = None
            profile_id: Optional[uuid.UUID] = None

            if u.role == RoleEnum.STUDENT:
                student_row = await self.db.execute(
                    select(Student).where(Student.user_id == u.id)
                )
                student = student_row.scalar_one_or_none()
                profile_created = student is not None
                if student:
                    profile_id = student.id
                    suggested_identifier = student.admission_number
                    mapping_count = await self.db.execute(
                        select(func.count(StudentYearMapping.id)).where(
                            StudentYearMapping.student_id == student.id,
                            StudentYearMapping.status == EnrollmentStatus.ACTIVE,
                        )
                    )
                    enrollment_completed = (mapping_count.scalar_one() or 0) > 0
                if not profile_created:
                    pending_reason = "Student profile not created"
                elif not enrollment_completed:
                    pending_reason = "Class/section assignment pending"

            elif u.role == RoleEnum.TEACHER:
                teacher_row = await self.db.execute(
                    select(Teacher).where(Teacher.user_id == u.id)
                )
                teacher = teacher_row.scalar_one_or_none()
                profile_created = teacher is not None
                if teacher:
                    profile_id = teacher.id
                    suggested_identifier = teacher.employee_code
                    assignment_count = await self.db.execute(
                        select(func.count(TeacherClassSubject.id)).where(
                            TeacherClassSubject.teacher_id == teacher.id,
                            TeacherClassSubject.academic_year_id == active_year.id,
                        )
                    )
                    enrollment_completed = (assignment_count.scalar_one() or 0) > 0
                if not profile_created:
                    pending_reason = "Teacher profile not created"
                elif not enrollment_completed:
                    pending_reason = "Class/section/subject assignment pending"

            elif u.role == RoleEnum.PARENT:
                parent_row = await self.db.execute(
                    select(Parent).where(Parent.user_id == u.id)
                )
                parent = parent_row.scalar_one_or_none()
                profile_created = parent is not None
                if parent:
                    profile_id = parent.id
                    suggested_identifier = parent.parent_code
                    child_count = await self.db.execute(
                        select(func.count(Student.id)).where(Student.parent_id == parent.id)
                    )
                    enrollment_completed = (child_count.scalar_one() or 0) > 0
                if not profile_created:
                    pending_reason = "Parent profile not created"
                elif not enrollment_completed:
                    pending_reason = "Child linking pending"

            elif u.role in (RoleEnum.PRINCIPAL, RoleEnum.TRUSTEE):
                profile_created = True
                enrollment_completed = True
                pending_reason = None

            else:
                profile_created = True
                enrollment_completed = True

            enrollment_pending = not enrollment_completed
            if pending_only and not enrollment_pending:
                continue

            items.append(
                {
                    "user_id": u.id,
                    "profile_id": profile_id,
                    "full_name": u.full_name,
                    "email": u.email,
                    "phone": u.phone,
                    "role": u.role,
                    "status": u.status,
                    "school_id": u.school_id,
                    "profile_created": profile_created,
                    "enrollment_completed": enrollment_completed,
                    "enrollment_pending": enrollment_pending,
                    "pending_reason": pending_reason,
                    "suggested_identifier": suggested_identifier,
                    "academic_year_id": active_year.id,
                    "academic_year_name": active_year.name,
                    "approved_at": u.approved_at,
                    "created_at": u.created_at,
                }
            )
        return items

    # ────────────────────────────────────────────────────────────
    # CREATE MAPPING
    # ────────────────────────────────────────────────────────────
    async def create_mapping(
        self,
        data: EnrollmentMappingCreate,
        actor: CurrentUser,
    ) -> StudentYearMapping:
        school_id = actor.school_id

        student = await self._load_student(data.student_id, school_id)
        await self._load_academic_year(data.academic_year_id, school_id)

        existing = await self.repo.get_by_student_year(data.student_id, data.academic_year_id)
        if existing:
            raise ConflictException(
                f"Student already has an enrollment mapping for this academic year. "
                f"Current status: {existing.status.value}"
            )

        std = await self._load_standard(data.standard_id, data.academic_year_id, school_id)

        section_name = None
        if data.section_id:
            section = await self._load_section(
                data.section_id, data.standard_id, data.academic_year_id
            )
            section_name = section.name

            enrolled_count = await self.repo.count_active_in_section(
                data.section_id, data.academic_year_id
            )
            if section.capacity and enrolled_count >= section.capacity:
                pass  # non-blocking capacity warning

        mapping = StudentYearMapping(
            student_id=data.student_id,
            school_id=school_id,
            academic_year_id=data.academic_year_id,
            standard_id=data.standard_id,
            section_id=data.section_id,
            section_name=section_name,
            roll_number=data.roll_number,
            status=EnrollmentStatus.ACTIVE,
            admission_type=data.admission_type,
            joined_on=data.joined_on or date.today(),
            created_by_id=actor.id,
            last_modified_by_id=actor.id,
        )
        self.db.add(mapping)
        await self.db.flush()

        await self._sync_student_flat_fields(student, mapping)

        await self.audit.log(
            action=AuditAction.STUDENT_ENROLLED,
            actor_id=actor.id,
            target_user_id=student.user_id,
            entity_type="StudentYearMapping",
            entity_id=str(mapping.id),
            school_id=school_id,
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
    # GET SINGLE MAPPING
    # ────────────────────────────────────────────────────────────
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
    # UPDATE MAPPING
    # ────────────────────────────────────────────────────────────
    async def update_mapping(
        self,
        mapping_id: uuid.UUID,
        data: EnrollmentMappingUpdate,
        actor: CurrentUser,
    ) -> StudentYearMapping:
        mapping = await self.repo.get_by_id(mapping_id)
        if not mapping or mapping.school_id != actor.school_id:
            raise NotFoundException("Enrollment mapping not found.")

        if mapping.status not in VALID_UPDATE_FROM:
            raise ValidationException(
                f"Cannot update mapping with status: {mapping.status.value}. "
                f"Must be ACTIVE or HOLD."
            )

        if data.standard_id:
            await self._load_standard(
                data.standard_id, mapping.academic_year_id, actor.school_id
            )
            mapping.standard_id = data.standard_id
        if data.section_id is not None:
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
        if data.admission_type is not None:
            mapping.admission_type = data.admission_type

        mapping.last_modified_by_id = actor.id
        await self.db.flush()

        student = await self._load_student(mapping.student_id, actor.school_id)
        await self._sync_student_flat_fields(student, mapping)

        await self.db.commit()
        await self.db.refresh(mapping)
        return mapping

    # ────────────────────────────────────────────────────────────
    # TRANSFER STUDENT (Phase 14/15)
    # In-year section OR class transfer — creates a distinct audit record
    # ────────────────────────────────────────────────────────────
    async def transfer_student(
        self,
        mapping_id: uuid.UUID,
        data: SectionTransferRequest,
        actor: CurrentUser,
    ) -> StudentYearMapping:
        mapping = await self.repo.get_by_id(mapping_id)
        if not mapping or mapping.school_id != actor.school_id:
            raise NotFoundException("Enrollment mapping not found.")

        if mapping.status not in VALID_UPDATE_FROM:
            raise ValidationException(
                f"Cannot transfer a student with status: {mapping.status.value}. "
                f"Student must be ACTIVE or HOLD."
            )

        old_standard_id = mapping.standard_id
        old_section_id = mapping.section_id
        old_section_name = mapping.section_name

        is_class_change = (data.new_standard_id != old_standard_id)

        # Validate new standard
        new_std = await self._load_standard(
            data.new_standard_id, mapping.academic_year_id, actor.school_id
        )

        # Validate new section (if provided)
        new_section_name: Optional[str] = None
        if data.new_section_id:
            new_section = await self._load_section(
                data.new_section_id, data.new_standard_id, mapping.academic_year_id
            )
            new_section_name = new_section.name

        before = {
            "standard_id": str(old_standard_id),
            "section_id": str(old_section_id) if old_section_id else None,
            "section_name": old_section_name,
        }
        after = {
            "standard_id": str(data.new_standard_id),
            "section_id": str(data.new_section_id) if data.new_section_id else None,
            "section_name": new_section_name,
        }

        mapping.standard_id = data.new_standard_id
        mapping.section_id = data.new_section_id
        mapping.section_name = new_section_name
        if data.effective_date and data.effective_date > date.today():
            raise ValidationException("Transfer effective date cannot be in the future.")
        if data.new_roll_number is not None:
            mapping.roll_number = data.new_roll_number
        mapping.last_modified_by_id = actor.id
        await self.db.flush()

        student = await self._load_student(mapping.student_id, actor.school_id)
        await self._sync_student_flat_fields(student, mapping)

        audit_action = (
            AuditAction.STUDENT_CLASS_TRANSFERRED
            if is_class_change
            else AuditAction.STUDENT_SECTION_TRANSFERRED
        )
        action_label = "class" if is_class_change else "section"

        await self.audit.log(
            action=audit_action,
            actor_id=actor.id,
            target_user_id=student.user_id,
            entity_type="StudentYearMapping",
            entity_id=str(mapping_id),
            school_id=actor.school_id,
            description=(
                f"{actor.full_name} transferred student '{student.admission_number}' "
                f"to {action_label} {new_std.name} Section {new_section_name or 'N/A'}. "
                f"Reason: {data.transfer_reason}. "
                f"Effective: {data.effective_date or date.today()}"
            ),
            before_state=before,
            after_state=after,
        )

        await self.db.commit()
        await self.db.refresh(mapping)
        return mapping

    # ────────────────────────────────────────────────────────────
    # EXIT STUDENT
    # ────────────────────────────────────────────────────────────
    async def exit_student(
        self,
        mapping_id: uuid.UUID,
        data: EnrollmentExitRequest,
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

        student = await self._load_student(mapping.student_id, actor.school_id)
        await self._sync_student_flat_fields(student, mapping)

        await self.audit.log(
            action=AuditAction.STUDENT_EXITED,
            actor_id=actor.id,
            target_user_id=student.user_id if student else None,
            entity_type="StudentYearMapping",
            entity_id=str(mapping_id),
            school_id=actor.school_id,
            description=(
                f"{actor.full_name} marked student as {data.status.value}. "
                f"Exit date: {data.left_on}. Reason: {data.exit_reason}"
            ),
            before_state=before,
            after_state={"status": data.status.value, "left_on": str(data.left_on)},
        )

        await self.db.commit()
        await self.db.refresh(mapping)
        return mapping

    # ────────────────────────────────────────────────────────────
    # COMPLETE MAPPING (year end)
    # ────────────────────────────────────────────────────────────
    async def complete_mapping(
        self,
        mapping_id: uuid.UUID,
        data: EnrollmentCompleteRequest,
        actor: CurrentUser,
    ) -> StudentYearMapping:
        mapping = await self.repo.get_by_id(mapping_id)
        if not mapping or mapping.school_id != actor.school_id:
            raise NotFoundException("Enrollment mapping not found.")

        if mapping.status != EnrollmentStatus.ACTIVE:
            raise ValidationException(
                f"Only ACTIVE mappings can be marked COMPLETED. "
                f"Current status: {mapping.status.value}"
            )
        if data.completed_on and data.completed_on > date.today():
            raise ValidationException("Completion date cannot be in the future.")

        before = {"status": mapping.status.value}
        mapping.status = EnrollmentStatus.COMPLETED
        mapping.last_modified_by_id = actor.id
        await self.db.flush()
        student = await self._load_student(mapping.student_id, actor.school_id)
        await self._sync_student_flat_fields(student, mapping)

        await self.audit.log(
            action=AuditAction.STUDENT_PROMOTED,
            actor_id=actor.id,
            target_user_id=None,
            entity_type="StudentYearMapping",
            entity_id=str(mapping_id),
            school_id=actor.school_id,
            description=(
                f"{actor.full_name} marked mapping {mapping_id} as COMPLETED "
                f"(year-end, eligible for promotion). "
                f"Completed on: {data.completed_on or date.today()}"
            ),
            before_state=before,
            after_state={"status": EnrollmentStatus.COMPLETED.value},
        )

        await self.db.commit()
        await self.db.refresh(mapping)
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
        std_row = await self.db.execute(
            select(Standard).where(Standard.id == standard_id)
        )
        std = std_row.scalar_one_or_none()
        std_name = std.name if std else str(standard_id)

        year_row = await self.db.execute(
            select(AcademicYear).where(AcademicYear.id == academic_year_id)
        )
        year = year_row.scalar_one_or_none()
        year_name = year.name if year else str(academic_year_id)

        section_name: Optional[str] = None
        if section_id:
            sec_row = await self.db.execute(
                select(Section).where(Section.id == section_id)
            )
            sec = sec_row.scalar_one_or_none()
            section_name = sec.name if sec else None

        filters = [
            StudentYearMapping.school_id == school_id,
            StudentYearMapping.standard_id == standard_id,
            StudentYearMapping.academic_year_id == academic_year_id,
        ]
        if section_id:
            filters.append(StudentYearMapping.section_id == section_id)

        stmt = (
            select(StudentYearMapping)
            .options(
                selectinload(StudentYearMapping.student).selectinload(Student.user)
            )
            .where(and_(*filters))
            .order_by(StudentYearMapping.roll_number)
        )
        rows = await self.db.execute(stmt)
        mappings = rows.scalars().all()

        responses = [self._to_response(m) for m in mappings]
        active_count = sum(1 for r in responses if r.status == EnrollmentStatus.ACTIVE)
        left_count = sum(1 for r in responses if r.status in (EnrollmentStatus.LEFT, EnrollmentStatus.TRANSFERRED))
        completed_count = sum(1 for r in responses if r.status == EnrollmentStatus.COMPLETED)

        return ClassRosterResponse(
            academic_year_id=academic_year_id,
            academic_year_name=year_name,
            standard_id=standard_id,
            standard_name=std_name,
            section_name=section_name,
            total_enrolled=len(responses),
            active_count=active_count,
            left_count=left_count,
            completed_count=completed_count,
            mappings=responses,
        )

    # ────────────────────────────────────────────────────────────
    # STUDENT ACADEMIC HISTORY (Phase 7 / 14)
    # ────────────────────────────────────────────────────────────
    async def get_student_history(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> StudentAcademicHistoryResponse:
        student = await self._load_student(student_id, school_id)

        stmt = (
            select(StudentYearMapping)
            .options(
                selectinload(StudentYearMapping.standard),
                selectinload(StudentYearMapping.section),
                selectinload(StudentYearMapping.academic_year),
            )
            .where(
                and_(
                    StudentYearMapping.student_id == student_id,
                    StudentYearMapping.school_id == school_id,
                )
            )
            .order_by(StudentYearMapping.joined_on.desc())
        )
        rows = await self.db.execute(stmt)
        mappings = rows.scalars().all()

        return StudentAcademicHistoryResponse(
            student_id=student_id,
            admission_number=student.admission_number,
            student_name=student.user.full_name if student.user else None,
            history=[self._to_response(m) for m in mappings],
        )

    # ────────────────────────────────────────────────────────────
    # ROLL NUMBER ASSIGNMENT
    # ────────────────────────────────────────────────────────────
    async def assign_roll_numbers(
        self,
        data: RollNumberAssignRequest,
        actor: CurrentUser,
    ) -> dict:
        filters = [
            StudentYearMapping.school_id == actor.school_id,
            StudentYearMapping.standard_id == data.standard_id,
            StudentYearMapping.section_id == data.section_id,
            StudentYearMapping.academic_year_id == data.academic_year_id,
            StudentYearMapping.status == EnrollmentStatus.ACTIVE,
        ]
        stmt = (
            select(StudentYearMapping)
            .options(selectinload(StudentYearMapping.student).selectinload(Student.user))
            .where(and_(*filters))
        )
        rows = await self.db.execute(stmt)
        mappings = list(rows.scalars().all())

        if data.policy == "AUTO_ALPHA":
            mappings.sort(
                key=lambda m: (m.student.user.full_name if m.student and m.student.user else "")
            )
            for idx, m in enumerate(mappings, start=1):
                m.roll_number = str(idx)
        elif data.policy == "AUTO_SEQ":
            mappings.sort(key=lambda m: m.joined_on or date.today())
            for idx, m in enumerate(mappings, start=1):
                m.roll_number = str(idx)
        elif data.policy == "MANUAL" and data.manual_assignments:
            roll_map = {item["mapping_id"]: item["roll_number"] for item in data.manual_assignments}
            for m in mappings:
                if str(m.id) in roll_map:
                    m.roll_number = roll_map[str(m.id)]

        await self.db.flush()
        await self.db.commit()

        return {
            "assigned_count": len(mappings),
            "policy": data.policy,
            "standard_id": str(data.standard_id),
            "section_id": str(data.section_id),
            "academic_year_id": str(data.academic_year_id),
        }

    # ────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ────────────────────────────────────────────────────────────

    async def _load_student(self, student_id: uuid.UUID, school_id: uuid.UUID) -> Student:
        stmt = (
            select(Student)
            .options(selectinload(Student.user))
            .where(and_(Student.id == student_id, Student.school_id == school_id))
        )
        row = await self.db.execute(stmt)
        student = row.scalar_one_or_none()
        if not student:
            raise NotFoundException("Student not found in this school.")
        return student

    async def _load_standard(
        self,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> Standard:
        stmt = select(Standard).where(
            and_(
                Standard.id == standard_id,
                Standard.school_id == school_id,
            )
        )
        row = await self.db.execute(stmt)
        std = row.scalar_one_or_none()
        if not std:
            raise NotFoundException("Standard/Class not found in this school.")
        if std.academic_year_id and std.academic_year_id != academic_year_id:
            raise ValidationException(
                "Selected class does not belong to the selected academic year."
            )
        return std

    async def _load_academic_year(self, academic_year_id: uuid.UUID, school_id: uuid.UUID) -> AcademicYear:
        row = await self.db.execute(
            select(AcademicYear).where(
                and_(
                    AcademicYear.id == academic_year_id,
                    AcademicYear.school_id == school_id,
                )
            )
        )
        year = row.scalar_one_or_none()
        if not year:
            raise NotFoundException("Academic year not found in this school.")
        return year

    async def _load_section(
        self,
        section_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> Section:
        stmt = select(Section).where(
            and_(
                Section.id == section_id,
                Section.standard_id == standard_id,
                Section.academic_year_id == academic_year_id,
            )
        )
        row = await self.db.execute(stmt)
        section = row.scalar_one_or_none()
        if not section:
            raise NotFoundException("Section not found for this class/year.")
        return section

    async def _sync_student_flat_fields(
        self, student: Student, mapping: StudentYearMapping
    ) -> None:
        """Keep Student denormalized flat fields synced to current ACTIVE mapping."""
        if mapping.status == EnrollmentStatus.ACTIVE:
            student.standard_id = mapping.standard_id
            student.section = mapping.section_name
            student.roll_number = mapping.roll_number
            student.academic_year_id = mapping.academic_year_id
            await self.db.flush()
            return

        active_stmt = (
            select(StudentYearMapping)
            .where(
                and_(
                    StudentYearMapping.student_id == student.id,
                    StudentYearMapping.school_id == student.school_id,
                    StudentYearMapping.status == EnrollmentStatus.ACTIVE,
                )
            )
            .order_by(
                StudentYearMapping.joined_on.desc(),
                StudentYearMapping.created_at.desc(),
            )
            .limit(1)
        )
        active_row = await self.db.execute(active_stmt)
        active_mapping = active_row.scalar_one_or_none()
        if active_mapping:
            student.standard_id = active_mapping.standard_id
            student.section = active_mapping.section_name
            student.roll_number = active_mapping.roll_number
            student.academic_year_id = active_mapping.academic_year_id
        else:
            student.standard_id = None
            student.section = None
            student.roll_number = None
            student.academic_year_id = None
        await self.db.flush()

    def _to_response(self, m: StudentYearMapping) -> EnrollmentMappingResponse:
        student_name = None
        admission_number = None
        if m.student:
            admission_number = m.student.admission_number
            if m.student.user:
                student_name = m.student.user.full_name

        standard_name = m.standard.name if m.standard else None
        academic_year_name = m.academic_year.name if m.academic_year else None

        return EnrollmentMappingResponse(
            id=m.id,
            student_id=m.student_id,
            school_id=m.school_id,
            academic_year_id=m.academic_year_id,
            standard_id=m.standard_id,
            section_id=m.section_id,
            section_name=m.section_name,
            roll_number=m.roll_number,
            status=m.status,
            admission_type=m.admission_type,
            joined_on=m.joined_on,
            left_on=m.left_on,
            exit_reason=m.exit_reason,
            student_name=student_name,
            admission_number=admission_number,
            standard_name=standard_name,
            academic_year_name=academic_year_name,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

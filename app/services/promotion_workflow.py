"""Phase 7 promotion workflow service."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import CurrentUser
from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.academic_year import AcademicYear
from app.models.masters import Standard
from app.models.section import Section
from app.models.student import Student
from app.models.student_year_mapping import StudentYearMapping
from app.models.teacher_class_subject import TeacherClassSubject
from app.models.teacher import Teacher
from app.models.parent import Parent
from app.models.user import User
from app.schemas.enrollment import EnrollmentMappingCreate
from app.schemas.promotion_workflow import (
    CopyTeacherAssignmentsResponse,
    PromotionExecuteResponse,
    PromotionExecuteResultItem,
    PromotionPreviewItem,
    PromotionPreviewResponse,
    SingleReenrollResponse,
    TeacherReenrollResponse,
)
from app.services.audit_log import AuditLogService
from app.services.enrollment import EnrollmentService
from app.utils.enums import AdmissionType, AuditAction, EnrollmentStatus, PromotionDecision


class PromotionWorkflowService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = AuditLogService(db)
        self.enrollment = EnrollmentService(db)

    async def preview_promotion(
        self,
        source_year_id: uuid.UUID,
        target_year_id: uuid.UUID,
        school_id: uuid.UUID,
        standard_id: uuid.UUID | None = None,
        section_id: uuid.UUID | None = None,
    ):
        source_year, target_year = await self._load_year_pair(
            school_id, source_year_id, target_year_id
        )
        source_standards = await self._load_standards_by_year(school_id, source_year_id)
        target_standards = await self._load_standards_by_year(school_id, target_year_id)
        target_by_level = {s.level: s for s in target_standards}
        max_source_level = max((s.level for s in source_standards), default=0)
        section_cache: dict[tuple[uuid.UUID, str], tuple[Optional[uuid.UUID], Optional[str]]] = {}

        stmt = (
            select(StudentYearMapping)
            .options(
                selectinload(StudentYearMapping.student).selectinload(Student.user),
                selectinload(StudentYearMapping.standard),
            )
            .where(
                and_(
                    StudentYearMapping.school_id == school_id,
                    StudentYearMapping.academic_year_id == source_year_id,
                    StudentYearMapping.status.in_(
                        [EnrollmentStatus.ACTIVE, EnrollmentStatus.COMPLETED]
                    ),
                )
            )
            .order_by(StudentYearMapping.created_at.asc())
        )
        if standard_id:
            stmt = stmt.where(StudentYearMapping.standard_id == standard_id)
        if section_id:
            stmt = stmt.where(StudentYearMapping.section_id == section_id)

        rows = await self.db.execute(stmt)
        mappings = rows.scalars().all()

        items: list[PromotionPreviewItem] = []
        warning_count = 0
        promotable_count = 0
        for mapping in mappings:
            current_standard = mapping.standard
            if current_standard is None:
                continue

            target_std = target_by_level.get(current_standard.level + 1)
            suggested_decision = PromotionDecision.PROMOTE
            has_warning = False
            warning_message: Optional[str] = None
            suggested_next_standard_id: Optional[uuid.UUID] = None
            suggested_next_standard_name: Optional[str] = None
            suggested_next_section_id: Optional[uuid.UUID] = None
            suggested_next_section_name: Optional[str] = None

            if target_std is not None:
                suggested_next_standard_id = target_std.id
                suggested_next_standard_name = target_std.name
                if mapping.section_name:
                    cache_key = (target_std.id, mapping.section_name)
                    cached = section_cache.get(cache_key)
                    if cached is None:
                        cached = await self._resolve_target_section(
                            school_id=school_id,
                            target_year_id=target_year_id,
                            target_standard_id=target_std.id,
                            requested_section_id=None,
                            fallback_section_name=mapping.section_name,
                        )
                        section_cache[cache_key] = cached
                    suggested_next_section_id, suggested_next_section_name = cached
                promotable_count += 1
            elif current_standard.level >= max_source_level:
                suggested_decision = PromotionDecision.GRADUATE
            else:
                suggested_decision = PromotionDecision.REPEAT
                has_warning = True
                warning_message = (
                    "Next class is not configured in target academic year. "
                    "Review before execute."
                )
                warning_count += 1

            student = mapping.student
            items.append(
                PromotionPreviewItem(
                    student_id=mapping.student_id,
                    mapping_id=mapping.id,
                    admission_number=student.admission_number if student else None,
                    student_name=student.user.full_name
                    if student and student.user
                    else None,
                    current_standard_id=mapping.standard_id,
                    current_standard_name=current_standard.name,
                    current_section_name=mapping.section_name,
                    current_status=mapping.status,
                    suggested_decision=suggested_decision,
                    suggested_next_standard_id=suggested_next_standard_id,
                    suggested_next_standard_name=suggested_next_standard_name,
                    suggested_next_section_id=suggested_next_section_id,
                    suggested_next_section_name=suggested_next_section_name,
                    has_warning=has_warning,
                    warning_message=warning_message,
                )
            )

        return PromotionPreviewResponse(
            source_year_id=source_year.id,
            source_year_name=source_year.name,
            target_year_id=target_year.id,
            target_year_name=target_year.name,
            total_students=len(items),
            promotable_count=promotable_count,
            warning_count=warning_count,
            items=items,
        )

    async def execute_promotion(self, data, current_user: CurrentUser):
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("School context required")
        await self._load_year_pair(school_id, data.source_year_id, data.target_year_id)

        seen_mappings: set[uuid.UUID] = set()
        seen_students: set[uuid.UUID] = set()
        promoted = 0
        repeated = 0
        graduated = 0
        skipped = 0
        errors = 0
        results: list[PromotionExecuteResultItem] = []

        for item in data.items:
            if item.mapping_id in seen_mappings or item.student_id in seen_students:
                raise ValidationException("Duplicate student/mapping found in execute payload")
            seen_mappings.add(item.mapping_id)
            seen_students.add(item.student_id)

            mapping = await self._load_mapping_for_source(
                school_id, data.source_year_id, item.mapping_id, item.student_id
            )
            student = mapping.student

            try:
                if item.decision == PromotionDecision.SKIP:
                    skipped += 1
                    results.append(
                        PromotionExecuteResultItem(
                            student_id=item.student_id,
                            admission_number=student.admission_number if student else None,
                            student_name=student.user.full_name
                            if student and student.user
                            else None,
                            decision=item.decision,
                            old_mapping_id=mapping.id,
                            old_status=mapping.status,
                            new_mapping_id=None,
                        )
                    )
                    continue

                if item.decision in (PromotionDecision.PROMOTE, PromotionDecision.REPEAT):
                    if not item.target_standard_id:
                        raise ValidationException(
                            "target_standard_id is required for PROMOTE/REPEAT"
                        )
                    target_standard = await self._load_standard_for_year(
                        school_id, item.target_standard_id, data.target_year_id
                    )
                    target_section_id, target_section_name = await self._resolve_target_section(
                        school_id=school_id,
                        target_year_id=data.target_year_id,
                        target_standard_id=item.target_standard_id,
                        requested_section_id=item.target_section_id,
                        fallback_section_name=mapping.section_name,
                    )
                    existing = await self._get_student_year_mapping(
                        item.student_id, data.target_year_id
                    )
                    if existing:
                        raise ConflictException(
                            "Student already has enrollment in target academic year"
                        )

                    new_mapping = StudentYearMapping(
                        student_id=item.student_id,
                        school_id=school_id,
                        academic_year_id=data.target_year_id,
                        standard_id=target_standard.id,
                        section_id=target_section_id,
                        section_name=target_section_name,
                        roll_number=item.roll_number,
                        status=EnrollmentStatus.ACTIVE,
                        admission_type=mapping.admission_type or AdmissionType.READMISSION,
                        joined_on=date.today(),
                        created_by_id=current_user.id,
                        last_modified_by_id=current_user.id,
                    )
                    self.db.add(new_mapping)
                    await self.db.flush()

                    mapping.status = (
                        EnrollmentStatus.PROMOTED
                        if item.decision == PromotionDecision.PROMOTE
                        else EnrollmentStatus.REPEATED
                    )
                    mapping.next_year_mapping_id = new_mapping.id
                    mapping.last_modified_by_id = current_user.id
                    await self.db.flush()

                    if student:
                        student.standard_id = new_mapping.standard_id
                        student.section = new_mapping.section_name
                        student.roll_number = new_mapping.roll_number
                        student.academic_year_id = new_mapping.academic_year_id
                        await self.db.flush()
                        await self._mark_user_reenrolled_to_year(
                            student.user_id,
                            data.target_year_id,
                        )
                        await self._mark_parent_reenrolled_for_student(
                            student,
                            data.target_year_id,
                        )

                    await self.audit.log(
                        action=AuditAction.STUDENT_PROMOTED,
                        actor_id=current_user.id,
                        target_user_id=student.user_id if student else None,
                        entity_type="StudentYearMapping",
                        entity_id=str(mapping.id),
                        school_id=school_id,
                        description=(
                            f"Promotion workflow decision={item.decision.value} "
                            f"for student {student.admission_number if student else item.student_id}."
                        ),
                        after_state={
                            "old_status": mapping.status.value,
                            "new_mapping_id": str(new_mapping.id),
                            "target_standard_id": str(target_standard.id),
                        },
                    )

                    if item.decision == PromotionDecision.PROMOTE:
                        promoted += 1
                    else:
                        repeated += 1
                    results.append(
                        PromotionExecuteResultItem(
                            student_id=item.student_id,
                            admission_number=student.admission_number if student else None,
                            student_name=student.user.full_name
                            if student and student.user
                            else None,
                            decision=item.decision,
                            old_mapping_id=mapping.id,
                            old_status=mapping.status,
                            new_mapping_id=new_mapping.id,
                        )
                    )
                    continue

                if item.decision == PromotionDecision.GRADUATE:
                    mapping.status = EnrollmentStatus.GRADUATED
                    mapping.last_modified_by_id = current_user.id
                    await self.db.flush()
                    graduated += 1
                    await self.audit.log(
                        action=AuditAction.STUDENT_PROMOTED,
                        actor_id=current_user.id,
                        target_user_id=student.user_id if student else None,
                        entity_type="StudentYearMapping",
                        entity_id=str(mapping.id),
                        school_id=school_id,
                        description=(
                            f"Promotion workflow decision=GRADUATE for "
                            f"student {student.admission_number if student else item.student_id}."
                        ),
                        after_state={"old_status": mapping.status.value},
                    )
                    results.append(
                        PromotionExecuteResultItem(
                            student_id=item.student_id,
                            admission_number=student.admission_number if student else None,
                            student_name=student.user.full_name
                            if student and student.user
                            else None,
                            decision=item.decision,
                            old_mapping_id=mapping.id,
                            old_status=mapping.status,
                            new_mapping_id=None,
                        )
                    )
                    continue

                raise ValidationException(f"Unsupported decision: {item.decision}")
            except Exception as ex:
                errors += 1
                results.append(
                    PromotionExecuteResultItem(
                        student_id=item.student_id,
                        admission_number=student.admission_number if student else None,
                        student_name=student.user.full_name if student and student.user else None,
                        decision=item.decision,
                        old_mapping_id=mapping.id,
                        old_status=mapping.status,
                        new_mapping_id=None,
                        error=str(ex),
                    )
                )

        await self.db.commit()
        return PromotionExecuteResponse(
            source_year_id=data.source_year_id,
            target_year_id=data.target_year_id,
            promoted_count=promoted,
            repeated_count=repeated,
            graduated_count=graduated,
            skipped_count=skipped,
            error_count=errors,
            results=results,
        )

    async def reenroll_student(self, student_id: uuid.UUID, data, current_user: CurrentUser):
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("School context required")
        await self._load_standard_for_year(school_id, data.standard_id, data.target_year_id)
        existing = await self._get_student_year_mapping(student_id, data.target_year_id)
        if existing:
            raise ConflictException("Student already enrolled in target academic year")

        created = await self.enrollment.create_mapping(
            EnrollmentMappingCreate(
                student_id=student_id,
                academic_year_id=data.target_year_id,
                standard_id=data.standard_id,
                section_id=data.section_id,
                roll_number=data.roll_number,
                joined_on=data.joined_on or date.today(),
                admission_type=AdmissionType(data.admission_type),
            ),
            current_user,
        )
        student = created.student
        if student and student.user_id:
            await self._mark_user_reenrolled_to_year(
                student.user_id,
                data.target_year_id,
            )
            await self._mark_parent_reenrolled_for_student(
                student,
                data.target_year_id,
            )
            await self.db.commit()
        return SingleReenrollResponse(
            student_id=created.student_id,
            admission_number=student.admission_number if student else None,
            student_name=student.user.full_name if student and student.user else None,
            new_mapping_id=created.id,
            target_year_id=created.academic_year_id,
            standard_name=created.standard.name if created.standard else None,
            section_name=created.section_name,
        )

    async def copy_teacher_assignments(self, data, current_user: CurrentUser):
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("School context required")
        await self._load_year_pair(school_id, data.source_year_id, data.target_year_id)

        source_standards = await self._load_standards_by_year(school_id, data.source_year_id)
        target_standards = await self._load_standards_by_year(school_id, data.target_year_id)
        source_by_id = {s.id: s for s in source_standards}
        target_by_level = {s.level: s for s in target_standards}

        rows = await self.db.execute(
            select(TeacherClassSubject).where(
                TeacherClassSubject.academic_year_id == data.source_year_id
            )
        )
        source_assignments = rows.scalars().all()
        copied = 0
        skipped = 0
        errors = 0

        for assignment in source_assignments:
            try:
                src_std = source_by_id.get(assignment.standard_id)
                if not src_std:
                    skipped += 1
                    continue
                target_std = target_by_level.get(src_std.level)
                if not target_std:
                    skipped += 1
                    continue

                existing_stmt = select(TeacherClassSubject).where(
                    and_(
                        TeacherClassSubject.academic_year_id == data.target_year_id,
                        TeacherClassSubject.standard_id == target_std.id,
                        TeacherClassSubject.section == assignment.section,
                        TeacherClassSubject.subject_id == assignment.subject_id,
                    )
                )
                existing_rows = await self.db.execute(existing_stmt)
                existing = existing_rows.scalars().all()

                if existing and not data.overwrite_existing:
                    skipped += 1
                    continue

                if existing and data.overwrite_existing:
                    await self.db.execute(
                        delete(TeacherClassSubject).where(
                            and_(
                                TeacherClassSubject.academic_year_id == data.target_year_id,
                                TeacherClassSubject.standard_id == target_std.id,
                                TeacherClassSubject.section == assignment.section,
                                TeacherClassSubject.subject_id == assignment.subject_id,
                            )
                        )
                    )

                self.db.add(
                    TeacherClassSubject(
                        teacher_id=assignment.teacher_id,
                        standard_id=target_std.id,
                        section=assignment.section,
                        subject_id=assignment.subject_id,
                        academic_year_id=data.target_year_id,
                    )
                )
                copied += 1
            except Exception:
                errors += 1

        await self.audit.log(
            action=AuditAction.TEACHER_ASSIGNMENT_COPIED,
            actor_id=current_user.id,
            target_user_id=None,
            entity_type="TeacherClassSubject",
            school_id=school_id,
            description=(
                f"Copied teacher assignments from {data.source_year_id} to "
                f"{data.target_year_id}. copied={copied}, skipped={skipped}, errors={errors}"
            ),
        )
        await self.db.commit()
        return CopyTeacherAssignmentsResponse(
            source_year_id=data.source_year_id,
            target_year_id=data.target_year_id,
            copied_count=copied,
            skipped_count=skipped,
            error_count=errors,
        )

    async def reenroll_teacher_assignments(
        self,
        teacher_id: uuid.UUID,
        data,
        current_user: CurrentUser,
    ) -> TeacherReenrollResponse:
        school_id = current_user.school_id
        if not school_id:
            raise ValidationException("School context required")
        await self._load_year_pair(school_id, data.source_year_id, data.target_year_id)
        teacher_row = await self.db.execute(
            select(Teacher).where(
                and_(Teacher.id == teacher_id, Teacher.school_id == school_id)
            )
        )
        teacher = teacher_row.scalar_one_or_none()
        if not teacher:
            raise NotFoundException("Teacher not found in this school")

        source_standards = await self._load_standards_by_year(school_id, data.source_year_id)
        target_standards = await self._load_standards_by_year(school_id, data.target_year_id)
        source_by_id = {s.id: s for s in source_standards}
        target_by_level = {s.level: s for s in target_standards}

        rows = await self.db.execute(
            select(TeacherClassSubject).where(
                and_(
                    TeacherClassSubject.teacher_id == teacher_id,
                    TeacherClassSubject.academic_year_id == data.source_year_id,
                )
            )
        )
        source_assignments = rows.scalars().all()
        copied = 0
        skipped = 0
        errors = 0

        for assignment in source_assignments:
            try:
                src_std = source_by_id.get(assignment.standard_id)
                if not src_std:
                    skipped += 1
                    continue
                target_std = target_by_level.get(src_std.level)
                if not target_std:
                    skipped += 1
                    continue

                existing_stmt = select(TeacherClassSubject).where(
                    and_(
                        TeacherClassSubject.teacher_id == teacher_id,
                        TeacherClassSubject.academic_year_id == data.target_year_id,
                        TeacherClassSubject.standard_id == target_std.id,
                        TeacherClassSubject.section == assignment.section,
                        TeacherClassSubject.subject_id == assignment.subject_id,
                    )
                )
                existing_rows = await self.db.execute(existing_stmt)
                existing = existing_rows.scalars().all()
                if existing and not data.overwrite_existing:
                    skipped += 1
                    continue
                if existing and data.overwrite_existing:
                    await self.db.execute(
                        delete(TeacherClassSubject).where(
                            and_(
                                TeacherClassSubject.teacher_id == teacher_id,
                                TeacherClassSubject.academic_year_id == data.target_year_id,
                                TeacherClassSubject.standard_id == target_std.id,
                                TeacherClassSubject.section == assignment.section,
                                TeacherClassSubject.subject_id == assignment.subject_id,
                            )
                        )
                    )
                self.db.add(
                    TeacherClassSubject(
                        teacher_id=teacher_id,
                        standard_id=target_std.id,
                        section=assignment.section,
                        subject_id=assignment.subject_id,
                        academic_year_id=data.target_year_id,
                    )
                )
                copied += 1
            except Exception:
                errors += 1

        await self.audit.log(
            action=AuditAction.TEACHER_ASSIGNMENT_COPIED,
            actor_id=current_user.id,
            target_user_id=teacher.user_id,
            entity_type="TeacherClassSubject",
            school_id=school_id,
            description=(
                f"Teacher re-enrolled assignments for teacher_id={teacher_id} "
                f"from {data.source_year_id} to {data.target_year_id}. "
                f"copied={copied}, skipped={skipped}, errors={errors}"
            ),
        )
        await self.db.commit()
        await self._mark_user_reenrolled_to_year(teacher.user_id, data.target_year_id)
        await self.db.commit()
        return TeacherReenrollResponse(
            teacher_id=teacher_id,
            source_year_id=data.source_year_id,
            target_year_id=data.target_year_id,
            copied_count=copied,
            skipped_count=skipped,
            error_count=errors,
        )

    async def _mark_user_reenrolled_to_year(
        self,
        user_id: Optional[uuid.UUID],
        academic_year_id: uuid.UUID,
    ) -> None:
        if user_id is None:
            return
        row = await self.db.execute(select(User).where(User.id == user_id))
        user = row.scalar_one_or_none()
        if not user:
            return
        submitted = dict(user.submitted_data or {})
        history = submitted.get("reenrollment_history")
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "academic_year_id": str(academic_year_id),
                "at": date.today().isoformat(),
            }
        )
        submitted["reenrollment_history"] = history[-10:]
        submitted["academic_year_id"] = str(academic_year_id)
        user.submitted_data = submitted
        await self.db.flush()

    async def _mark_parent_reenrolled_for_student(
        self,
        student: Optional[Student],
        academic_year_id: uuid.UUID,
    ) -> None:
        if student is None or student.parent_id is None:
            return
        parent_row = await self.db.execute(
            select(Parent).where(Parent.id == student.parent_id)
        )
        parent = parent_row.scalar_one_or_none()
        if not parent:
            return
        await self._mark_user_reenrolled_to_year(parent.user_id, academic_year_id)

    async def _load_year_pair(
        self, school_id: uuid.UUID, source_year_id: uuid.UUID, target_year_id: uuid.UUID
    ) -> tuple[AcademicYear, AcademicYear]:
        if source_year_id == target_year_id:
            raise ValidationException("Source and target academic years must be different")
        s = await self.db.execute(
            select(AcademicYear).where(
                and_(AcademicYear.id == source_year_id, AcademicYear.school_id == school_id)
            )
        )
        source_year = s.scalar_one_or_none()
        if not source_year:
            raise NotFoundException("Source academic year not found")
        t = await self.db.execute(
            select(AcademicYear).where(
                and_(AcademicYear.id == target_year_id, AcademicYear.school_id == school_id)
            )
        )
        target_year = t.scalar_one_or_none()
        if not target_year:
            raise NotFoundException("Target academic year not found")
        return source_year, target_year

    async def _load_standards_by_year(
        self, school_id: uuid.UUID, year_id: uuid.UUID
    ) -> list[Standard]:
        rows = await self.db.execute(
            select(Standard).where(
                and_(Standard.school_id == school_id, Standard.academic_year_id == year_id)
            )
        )
        return list(rows.scalars().all())

    async def _load_mapping_for_source(
        self,
        school_id: uuid.UUID,
        source_year_id: uuid.UUID,
        mapping_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> StudentYearMapping:
        row = await self.db.execute(
            select(StudentYearMapping)
            .options(selectinload(StudentYearMapping.student).selectinload(Student.user))
            .where(
                and_(
                    StudentYearMapping.id == mapping_id,
                    StudentYearMapping.student_id == student_id,
                    StudentYearMapping.school_id == school_id,
                    StudentYearMapping.academic_year_id == source_year_id,
                )
            )
        )
        mapping = row.scalar_one_or_none()
        if not mapping:
            raise NotFoundException("Student mapping not found for source academic year")
        if mapping.status not in (EnrollmentStatus.ACTIVE, EnrollmentStatus.COMPLETED):
            raise ValidationException(
                f"Mapping {mapping.id} has invalid status for promotion: {mapping.status.value}"
            )
        return mapping

    async def _load_standard_for_year(
        self, school_id: uuid.UUID, standard_id: uuid.UUID, year_id: uuid.UUID
    ) -> Standard:
        row = await self.db.execute(
            select(Standard).where(
                and_(
                    Standard.id == standard_id,
                    Standard.school_id == school_id,
                    Standard.academic_year_id == year_id,
                )
            )
        )
        standard = row.scalar_one_or_none()
        if not standard:
            raise NotFoundException("Target class not found for target academic year")
        return standard

    async def _get_student_year_mapping(
        self, student_id: uuid.UUID, year_id: uuid.UUID
    ) -> Optional[StudentYearMapping]:
        row = await self.db.execute(
            select(StudentYearMapping).where(
                and_(
                    StudentYearMapping.student_id == student_id,
                    StudentYearMapping.academic_year_id == year_id,
                )
            )
        )
        return row.scalar_one_or_none()

    async def _resolve_target_section(
        self,
        school_id: uuid.UUID,
        target_year_id: uuid.UUID,
        target_standard_id: uuid.UUID,
        requested_section_id: Optional[uuid.UUID],
        fallback_section_name: Optional[str],
    ) -> tuple[Optional[uuid.UUID], Optional[str]]:
        if requested_section_id:
            row = await self.db.execute(
                select(Section).where(
                    and_(
                        Section.id == requested_section_id,
                        Section.school_id == school_id,
                        Section.academic_year_id == target_year_id,
                        Section.standard_id == target_standard_id,
                    )
                )
            )
            section = row.scalar_one_or_none()
            if not section:
                raise NotFoundException("Target section not found for class/year")
            return section.id, section.name

        if fallback_section_name:
            row = await self.db.execute(
                select(Section).where(
                    and_(
                        Section.school_id == school_id,
                        Section.academic_year_id == target_year_id,
                        Section.standard_id == target_standard_id,
                        Section.name == fallback_section_name,
                    )
                )
            )
            section = row.scalar_one_or_none()
            if section:
                return section.id, section.name
        return None, None

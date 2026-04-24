import uuid
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student_behaviour_log import StudentBehaviourLog
from app.utils.enums import IncidentType


class BehaviourRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> StudentBehaviourLog:
        obj = StudentBehaviourLog(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def list_by_student(
        self,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> list[StudentBehaviourLog]:
        result = await self.db.execute(
            select(StudentBehaviourLog).where(
                and_(
                    StudentBehaviourLog.school_id == school_id,
                    StudentBehaviourLog.student_id == student_id,
                )
            ).order_by(StudentBehaviourLog.incident_date.desc())
        )
        return list(result.scalars().all())

    async def list_by_school(
        self,
        school_id: uuid.UUID,
        student_id: Optional[uuid.UUID] = None,
        incident_type: Optional[IncidentType] = None,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
    ) -> list[StudentBehaviourLog]:
        stmt = select(StudentBehaviourLog).where(
            StudentBehaviourLog.school_id == school_id
        )
        if student_id is not None:
            stmt = stmt.where(StudentBehaviourLog.student_id == student_id)
        if incident_type is not None:
            stmt = stmt.where(StudentBehaviourLog.incident_type == incident_type)
        if standard_id is not None or (section is not None and section.strip()):
            from app.models.student import Student

            stmt = stmt.join(
                Student,
                and_(
                    Student.id == StudentBehaviourLog.student_id,
                    Student.school_id == school_id,
                ),
            )
            if standard_id is not None:
                stmt = stmt.where(Student.standard_id == standard_id)
            if section is not None and section.strip():
                stmt = stmt.where(
                    func.upper(func.trim(Student.section))
                    == func.upper(func.trim(section.strip()))
                )
        stmt = stmt.order_by(
            StudentBehaviourLog.incident_date.desc(),
            StudentBehaviourLog.created_at.desc(),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_for_teacher_scope(
        self,
        *,
        school_id: uuid.UUID,
        teacher_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        student_id: Optional[uuid.UUID] = None,
        incident_type: Optional[IncidentType] = None,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        own_logs_only: bool = False,
    ) -> list[StudentBehaviourLog]:
        from app.models.student import Student
        from app.models.teacher_class_subject import TeacherClassSubject

        stmt = (
            select(StudentBehaviourLog)
            .join(
                Student,
                and_(
                    Student.id == StudentBehaviourLog.student_id,
                    Student.school_id == school_id,
                ),
            )
            .join(
                TeacherClassSubject,
                and_(
                    TeacherClassSubject.teacher_id == teacher_id,
                    TeacherClassSubject.standard_id == Student.standard_id,
                    func.upper(func.trim(TeacherClassSubject.section))
                    == func.upper(func.trim(Student.section)),
                    TeacherClassSubject.academic_year_id == academic_year_id,
                ),
            )
            .where(StudentBehaviourLog.school_id == school_id)
            .where(StudentBehaviourLog.academic_year_id == academic_year_id)
            .order_by(
                StudentBehaviourLog.incident_date.desc(),
                StudentBehaviourLog.created_at.desc(),
            )
            .distinct()
        )
        if own_logs_only:
            stmt = stmt.where(StudentBehaviourLog.teacher_id == teacher_id)
        if student_id is not None:
            stmt = stmt.where(StudentBehaviourLog.student_id == student_id)
        if incident_type is not None:
            stmt = stmt.where(StudentBehaviourLog.incident_type == incident_type)
        if standard_id is not None:
            stmt = stmt.where(Student.standard_id == standard_id)
        if section is not None and section.strip():
            stmt = stmt.where(
                func.upper(func.trim(Student.section))
                == func.upper(func.trim(section.strip()))
            )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

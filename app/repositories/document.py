import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.student import Student
from app.utils.enums import DocumentStatus, DocumentType


class DocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Document:
        obj = Document(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, document_id: uuid.UUID, school_id: uuid.UUID) -> Optional[Document]:
        result = await self.db.execute(
            select(Document).where(
                and_(
                    Document.id == document_id,
                    Document.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_for_student(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        *,
        status: Optional[DocumentStatus] = None,
    ) -> list[Document]:
        stmt = select(Document).where(
            and_(
                Document.student_id == student_id,
                Document.school_id == school_id,
            )
        )
        if status is not None:
            stmt = stmt.where(Document.status == status)
        result = await self.db.execute(stmt.order_by(Document.updated_at.desc()))
        return list(result.scalars().all())

    async def list_for_school(
        self,
        school_id: uuid.UUID,
        *,
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        status: Optional[DocumentStatus] = None,
    ) -> list[Document]:
        stmt = (
            select(Document)
            .join(Student, Student.id == Document.student_id)
            .where(
                and_(
                    Document.school_id == school_id,
                    Student.school_id == school_id,
                )
            )
        )
        if academic_year_id is not None:
            stmt = stmt.where(Document.academic_year_id == academic_year_id)
        if standard_id is not None:
            stmt = stmt.where(Student.standard_id == standard_id)
        if section is not None:
            stmt = stmt.where(Student.section == section)
        if status is not None:
            stmt = stmt.where(Document.status == status)
        result = await self.db.execute(stmt.order_by(Document.updated_at.desc()))
        return list(result.scalars().all())

    async def list_for_students(
        self,
        student_ids: list[uuid.UUID],
        school_id: uuid.UUID,
    ) -> list[Document]:
        if not student_ids:
            return []
        result = await self.db.execute(
            select(Document).where(
                and_(
                    Document.student_id.in_(student_ids),
                    Document.school_id == school_id,
                )
            ).order_by(Document.requested_at.desc())
        )
        return list(result.scalars().all())

    async def update(self, doc: Document, data: dict) -> Document:
        for key, value in data.items():
            setattr(doc, key, value)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def get_by_student_type_year(
        self,
        *,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        document_type: DocumentType,
    ) -> Optional[Document]:
        result = await self.db.execute(
            select(Document)
            .where(
                and_(
                    Document.student_id == student_id,
                    Document.school_id == school_id,
                    Document.academic_year_id == academic_year_id,
                    Document.document_type == document_type,
                )
            )
            .order_by(Document.updated_at.desc())
        )
        return result.scalars().first()

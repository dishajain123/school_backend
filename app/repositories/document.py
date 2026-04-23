import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.utils.enums import DocumentStatus


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
        self, student_id: uuid.UUID, school_id: uuid.UUID
    ) -> list[Document]:
        result = await self.db.execute(
            select(Document).where(
                and_(
                    Document.student_id == student_id,
                    Document.school_id == school_id,
                )
            ).order_by(Document.requested_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_school(self, school_id: uuid.UUID) -> list[Document]:
        result = await self.db.execute(
            select(Document).where(
                Document.school_id == school_id,
            ).order_by(Document.requested_at.desc())
        )
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

    async def list_review_queue(
        self,
        school_id: uuid.UUID,
        *,
        student_id: Optional[uuid.UUID] = None,
    ) -> list[Document]:
        query = select(Document).where(
            and_(
                Document.school_id == school_id,
                Document.status == DocumentStatus.PROCESSING,
            )
        )
        if student_id is not None:
            query = query.where(Document.student_id == student_id)
        result = await self.db.execute(query.order_by(Document.requested_at.desc()))
        return list(result.scalars().all())

    async def update(self, doc: Document, data: dict) -> Document:
        for key, value in data.items():
            setattr(doc, key, value)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

import uuid

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.document import (
    DocumentRequest,
    DocumentResponse,
    DocumentListResponse,
    DocumentDownloadResponse,
)
from app.services.document import DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/request", response_model=DocumentResponse, status_code=201)
async def request_document(
    payload: DocumentRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("document:generate")),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).request_document(
        payload, current_user, background_tasks
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    student_id: uuid.UUID = Query(...),
    current_user: CurrentUser = Depends(require_permission("document:generate")),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).list_documents(student_id, current_user)


@router.get("/{document_id}/download", response_model=DocumentDownloadResponse)
async def download_document(
    document_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("document:generate")),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).download_document(document_id, current_user)

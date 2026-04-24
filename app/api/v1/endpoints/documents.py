import uuid
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission, get_current_user
from app.db.session import get_db
from app.schemas.document import (
    DocumentRequest,
    DocumentResponse,
    DocumentListResponse,
    DocumentDownloadResponse,
    DocumentVerifyRequest,
    DocumentRequirementsUpsertRequest,
    DocumentRequirementsResponse,
    DocumentRequirementStatusResponse,
)
from app.services.document import DocumentService
from app.utils.enums import DocumentType

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
    student_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).list_documents(student_id, current_user)


@router.get("/{document_id}/download", response_model=DocumentDownloadResponse)
async def download_document(
    document_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).download_document(document_id, current_user)


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    student_id: uuid.UUID = Form(...),
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).upload_document(
        student_id=student_id,
        document_type=document_type,
        file=file,
        current_user=current_user,
    )


@router.patch("/{document_id}/verify", response_model=DocumentResponse)
async def verify_document(
    document_id: uuid.UUID,
    payload: DocumentVerifyRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).verify_document(document_id, payload, current_user)


@router.get("/requirements", response_model=DocumentRequirementsResponse)
async def list_required_documents(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).list_required_documents(current_user)


@router.put("/requirements", response_model=DocumentRequirementsResponse)
async def upsert_required_documents(
    payload: DocumentRequirementsUpsertRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).upsert_required_documents(payload, current_user)


@router.get(
    "/requirements/status",
    response_model=list[DocumentRequirementStatusResponse],
)
async def list_required_documents_status(
    student_id: uuid.UUID = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).list_required_documents_for_student(
        student_id=student_id,
        current_user=current_user,
    )


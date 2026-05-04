import uuid
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
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
from app.utils.enums import DocumentType, DocumentStatus

router = APIRouter(prefix="/documents", tags=["Documents"])


def _legacy_status_filter_to_status(value: Optional[str]) -> Optional[DocumentStatus]:
    """Map deprecated status_filter query values to DocumentStatus."""
    if value is None:
        return None
    key = value.strip().lower()
    if key in {"", "all"}:
        return None
    mapping = {
        "not_uploaded": DocumentStatus.NOT_UPLOADED,
        "requested": DocumentStatus.REQUESTED,
        "pending": DocumentStatus.PENDING,
        "approved": DocumentStatus.APPROVED,
        "rejected": DocumentStatus.REJECTED,
    }
    mapped = mapping.get(key)
    if mapped is not None:
        return mapped
    try:
        return DocumentStatus[value.upper()]
    except KeyError:
        return None


def _parse_optional_uuid_param(value: Optional[str]) -> Optional[uuid.UUID]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"all", "null", "none"}:
        return None
    try:
        return uuid.UUID(cleaned)
    except ValueError:
        return None


@router.post("/request", response_model=DocumentResponse, status_code=201)
async def request_document(
    payload: DocumentRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).request_document(
        payload, current_user, background_tasks
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    student_id: Optional[str] = Query(None),
    academic_year_id: Optional[str] = Query(None),
    standard_id: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    status: Optional[DocumentStatus] = Query(
        None,
        description="Filter by DocumentStatus (e.g. PENDING, NOT_UPLOADED). Omit for all.",
    ),
    status_filter: Optional[str] = Query(
        None,
        description="Deprecated — use status=NOT_UPLOADED|PENDING|…",
    ),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resolved = status or _legacy_status_filter_to_status(status_filter)
    return await DocumentService(db).list_documents(
        _parse_optional_uuid_param(student_id),
        current_user,
        academic_year_id=_parse_optional_uuid_param(academic_year_id),
        standard_id=_parse_optional_uuid_param(standard_id),
        section=section,
        status=resolved,
    )


@router.get("/requirements", response_model=DocumentRequirementsResponse)
async def list_required_documents(
    academic_year_id: Optional[str] = Query(None),
    standard_id: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).list_required_documents(
        current_user,
        academic_year_id=_parse_optional_uuid_param(academic_year_id),
        standard_id=_parse_optional_uuid_param(standard_id),
    )


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
    note: Optional[str] = Form(None),
    academic_year_id: Optional[uuid.UUID] = Form(None),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).upload_document(
        student_id=student_id,
        document_type=document_type,
        file=file,
        note=note,
        current_user=current_user,
        academic_year_id=academic_year_id,
    )


@router.patch("/{document_id}/verify", response_model=DocumentResponse)
async def verify_document(
    document_id: uuid.UUID,
    payload: DocumentVerifyRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db).verify_document(document_id, payload, current_user)

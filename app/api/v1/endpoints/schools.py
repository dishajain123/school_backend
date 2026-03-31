import uuid
import math
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.school import SchoolCreate, SchoolUpdate, SchoolResponse, SchoolListResponse
from app.services.school import SchoolService

router = APIRouter(prefix="/schools", tags=["Schools"])


def get_school_service(db: AsyncSession = Depends(get_db)) -> SchoolService:
    return SchoolService(db)


@router.post("", response_model=SchoolResponse, status_code=201)
async def create_school(
    data: SchoolCreate,
    service: SchoolService = Depends(get_school_service),
):
    return await service.create_school(data)


@router.get("", response_model=SchoolListResponse)
async def list_schools(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = Query(None),
    service: SchoolService = Depends(get_school_service),
):
    schools, total = await service.list_schools(page=page, page_size=page_size, is_active=is_active)
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return SchoolListResponse(
        items=schools,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{school_id}", response_model=SchoolResponse)
async def get_school(
    school_id: uuid.UUID,
    service: SchoolService = Depends(get_school_service),
):
    return await service.get_school(school_id)


@router.patch("/{school_id}", response_model=SchoolResponse)
async def update_school(
    school_id: uuid.UUID,
    data: SchoolUpdate,
    service: SchoolService = Depends(get_school_service),
):
    return await service.update_school(school_id, data)


@router.patch("/{school_id}/deactivate", response_model=SchoolResponse)
async def deactivate_school(
    school_id: uuid.UUID,
    service: SchoolService = Depends(get_school_service),
):
    return await service.deactivate_school(school_id)
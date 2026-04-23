import uuid
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.gallery import (
    AlbumCreate,
    AlbumResponse,
    AlbumListResponse,
    PhotoResponse,
    PhotoListResponse,
    PhotoCommentCreate,
    PhotoInteractionResponse,
)
from app.services.gallery import GalleryService

router = APIRouter(prefix="/gallery", tags=["Gallery"])


@router.post("/albums", response_model=AlbumResponse, status_code=201)
async def create_album(
    payload: AlbumCreate,
    current_user: CurrentUser = Depends(require_permission("gallery:create")),
    db: AsyncSession = Depends(get_db),
):
    return await GalleryService(db).create_album(payload, current_user)


@router.post("/albums/{album_id}/photos", response_model=PhotoResponse, status_code=201)
async def upload_photo(
    album_id: uuid.UUID,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    current_user: CurrentUser = Depends(require_permission("gallery:create")),
    db: AsyncSession = Depends(get_db),
):
    return await GalleryService(db).upload_photo(
        album_id, current_user, file, caption
    )


@router.patch("/photos/{photo_id}/feature", response_model=PhotoResponse)
async def toggle_feature(
    photo_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("gallery:create")),
    db: AsyncSession = Depends(get_db),
):
    return await GalleryService(db).toggle_featured(photo_id, current_user)


@router.get("/albums", response_model=AlbumListResponse)
async def list_albums(
    current_user: CurrentUser = Depends(require_permission("gallery:read")),
    db: AsyncSession = Depends(get_db),
):
    return await GalleryService(db).list_albums(current_user)


@router.get("/albums/{album_id}/photos", response_model=PhotoListResponse)
async def list_photos(
    album_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("gallery:read")),
    db: AsyncSession = Depends(get_db),
):
    return await GalleryService(db).list_photos(album_id, current_user)


@router.get("/photos/{photo_id}/interactions", response_model=PhotoInteractionResponse)
async def get_photo_interactions(
    photo_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("gallery:read")),
    db: AsyncSession = Depends(get_db),
):
    return await GalleryService(db).get_photo_interactions(photo_id, current_user)


@router.put("/photos/{photo_id}/reaction", response_model=PhotoInteractionResponse)
async def react_to_photo(
    photo_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("gallery:read")),
    db: AsyncSession = Depends(get_db),
):
    return await GalleryService(db).add_reaction(photo_id, current_user)


@router.delete("/photos/{photo_id}/reaction", response_model=PhotoInteractionResponse)
async def remove_reaction(
    photo_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("gallery:read")),
    db: AsyncSession = Depends(get_db),
):
    return await GalleryService(db).remove_reaction(photo_id, current_user)


@router.post("/photos/{photo_id}/comments", response_model=PhotoInteractionResponse)
async def add_comment(
    photo_id: uuid.UUID,
    payload: PhotoCommentCreate,
    current_user: CurrentUser = Depends(require_permission("gallery:read")),
    db: AsyncSession = Depends(get_db),
):
    return await GalleryService(db).add_comment(photo_id, payload, current_user)

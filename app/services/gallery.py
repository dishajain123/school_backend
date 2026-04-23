import uuid
from pathlib import Path
from typing import Optional

from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException
from app.repositories.gallery import GalleryRepository
from app.schemas.gallery import (
    AlbumCreate,
    AlbumResponse,
    AlbumListResponse,
    PhotoResponse,
    PhotoListResponse,
    PhotoCommentCreate,
    PhotoCommentResponse,
    PhotoInteractionResponse,
)
from app.services.academic_year import get_active_year
from app.integrations.minio_client import minio_client
from app.utils.constants import MAX_FILE_SIZE_BYTES, ALLOWED_IMAGE_TYPES
from app.utils.enums import RoleEnum

GALLERY_BUCKET = "gallery"


class GalleryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = GalleryRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    def _album_response(self, album: AlbumResponse) -> AlbumResponse:
        if album.cover_photo_key:
            album.cover_photo_url = minio_client.generate_presigned_url(
                GALLERY_BUCKET, album.cover_photo_key
            )
        return album

    @staticmethod
    def _ensure_parent_or_student(current_user: CurrentUser) -> None:
        if current_user.role not in (RoleEnum.PARENT, RoleEnum.STUDENT):
            raise ForbiddenException(
                "Only parents and students can react or comment on gallery photos"
            )

    async def _interaction_response(
        self,
        photo_id: uuid.UUID,
        school_id: uuid.UUID,
        current_user_id: uuid.UUID,
    ) -> PhotoInteractionResponse:
        reactions_count = await self.repo.count_reactions(photo_id, school_id)
        own_reaction = await self.repo.get_reaction(photo_id, current_user_id, school_id)
        comments = await self.repo.list_comments(photo_id, school_id)
        comment_items = [PhotoCommentResponse.model_validate(c) for c in comments]
        return PhotoInteractionResponse(
            photo_id=photo_id,
            reactions_count=reactions_count,
            has_reacted=own_reaction is not None,
            comments=comment_items,
            total_comments=len(comment_items),
        )

    async def create_album(
        self,
        body: AlbumCreate,
        current_user: CurrentUser,
    ) -> AlbumResponse:
        school_id = self._ensure_school(current_user)
        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        album = await self.repo.create_album(
            {
                "event_name": body.event_name,
                "event_date": body.event_date,
                "description": body.description,
                "cover_photo_key": None,
                "created_by": current_user.id,
                "school_id": school_id,
                "academic_year_id": academic_year_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(album)
        return self._album_response(AlbumResponse.model_validate(album))

    async def list_albums(self, current_user: CurrentUser) -> AlbumListResponse:
        school_id = self._ensure_school(current_user)
        albums = await self.repo.list_albums(school_id)
        items = [self._album_response(AlbumResponse.model_validate(a)) for a in albums]
        return AlbumListResponse(items=items, total=len(items))

    async def upload_photo(
        self,
        album_id: uuid.UUID,
        current_user: CurrentUser,
        file: UploadFile,
        caption: Optional[str] = None,
    ) -> PhotoResponse:
        school_id = self._ensure_school(current_user)
        album = await self.repo.get_album_by_id(album_id, school_id)
        if not album:
            raise NotFoundException("Album")

        if not file or not file.filename:
            raise HTTPException(status_code=422, detail="File is required")

        # Accept common real-world image uploads even when clients send
        # generic MIME types (e.g. application/octet-stream).
        content_type = (file.content_type or "").strip().lower()
        extension = Path(file.filename).suffix.strip().lower()
        allowed_extensions = {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".gif",
            ".bmp",
            ".heic",
            ".heif",
        }
        is_image_upload = (
            (content_type in ALLOWED_IMAGE_TYPES)
            or content_type.startswith("image/")
            or (extension in allowed_extensions)
        )
        if not is_image_upload:
            raise HTTPException(
                status_code=422,
                detail="Only image uploads are allowed (jpg, jpeg, png, webp, gif, bmp, heic, heif)",
            )

        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="Uploaded file is empty")
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=422, detail="File too large")

        key = f"{school_id}/{album_id}/{uuid.uuid4()}_{file.filename}"
        minio_client.upload_file(
            bucket=GALLERY_BUCKET,
            key=key,
            file_bytes=content,
            content_type=file.content_type or "application/octet-stream",
        )

        photo = await self.repo.create_photo(
            {
                "album_id": album_id,
                "photo_key": key,
                "caption": caption,
                "uploaded_by": current_user.id,
                "is_featured": False,
                "school_id": school_id,
            }
        )

        # If no cover photo, set this as featured + cover
        if not album.cover_photo_key:
            await self.repo.update_photo(photo, {"is_featured": True})
            await self.repo.update_album(album, {"cover_photo_key": key})

        await self.db.commit()
        await self.db.refresh(photo)

        data = PhotoResponse.model_validate(photo)
        data.photo_url = minio_client.generate_presigned_url(GALLERY_BUCKET, photo.photo_key)
        return data

    async def list_photos(
        self, album_id: uuid.UUID, current_user: CurrentUser
    ) -> PhotoListResponse:
        school_id = self._ensure_school(current_user)
        album = await self.repo.get_album_by_id(album_id, school_id)
        if not album:
            raise NotFoundException("Album")

        photos = await self.repo.list_photos(album_id, school_id)
        items = []
        for p in photos:
            data = PhotoResponse.model_validate(p)
            data.photo_url = minio_client.generate_presigned_url(GALLERY_BUCKET, p.photo_key)
            items.append(data)
        return PhotoListResponse(items=items, total=len(items))

    async def toggle_featured(
        self,
        photo_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> PhotoResponse:
        school_id = self._ensure_school(current_user)
        photo = await self.repo.get_photo_by_id(photo_id, school_id)
        if not photo:
            raise NotFoundException("Photo")

        new_featured = not photo.is_featured
        updated = await self.repo.update_photo(photo, {"is_featured": new_featured})

        album = await self.repo.get_album_by_id(photo.album_id, school_id)
        if album:
            if new_featured:
                await self.repo.update_album(album, {"cover_photo_key": photo.photo_key})
            elif album.cover_photo_key == photo.photo_key:
                await self.repo.update_album(album, {"cover_photo_key": None})

        await self.db.commit()
        await self.db.refresh(updated)
        data = PhotoResponse.model_validate(updated)
        data.photo_url = minio_client.generate_presigned_url(GALLERY_BUCKET, updated.photo_key)
        return data

    async def get_photo_interactions(
        self,
        photo_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> PhotoInteractionResponse:
        school_id = self._ensure_school(current_user)
        photo = await self.repo.get_photo_by_id(photo_id, school_id)
        if not photo:
            raise NotFoundException("Photo")
        return await self._interaction_response(photo_id, school_id, current_user.id)

    async def add_reaction(
        self,
        photo_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> PhotoInteractionResponse:
        school_id = self._ensure_school(current_user)
        self._ensure_parent_or_student(current_user)

        photo = await self.repo.get_photo_by_id(photo_id, school_id)
        if not photo:
            raise NotFoundException("Photo")

        existing = await self.repo.get_reaction(photo_id, current_user.id, school_id)
        if existing:
            await self.repo.update_reaction(existing, {"reaction": "LIKE"})
        else:
            await self.repo.create_reaction(
                {
                    "photo_id": photo_id,
                    "reacted_by": current_user.id,
                    "reactor_role": current_user.role,
                    "reaction": "LIKE",
                    "school_id": school_id,
                }
            )

        await self.db.commit()
        return await self._interaction_response(photo_id, school_id, current_user.id)

    async def remove_reaction(
        self,
        photo_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> PhotoInteractionResponse:
        school_id = self._ensure_school(current_user)
        self._ensure_parent_or_student(current_user)

        photo = await self.repo.get_photo_by_id(photo_id, school_id)
        if not photo:
            raise NotFoundException("Photo")

        existing = await self.repo.get_reaction(photo_id, current_user.id, school_id)
        if existing:
            await self.repo.delete_reaction(existing)

        await self.db.commit()
        return await self._interaction_response(photo_id, school_id, current_user.id)

    async def add_comment(
        self,
        photo_id: uuid.UUID,
        body: PhotoCommentCreate,
        current_user: CurrentUser,
    ) -> PhotoInteractionResponse:
        school_id = self._ensure_school(current_user)
        self._ensure_parent_or_student(current_user)

        photo = await self.repo.get_photo_by_id(photo_id, school_id)
        if not photo:
            raise NotFoundException("Photo")

        await self.repo.create_comment(
            {
                "photo_id": photo_id,
                "comment": body.comment.strip(),
                "commented_by": current_user.id,
                "commenter_role": current_user.role,
                "school_id": school_id,
            }
        )

        await self.db.commit()
        return await self._interaction_response(photo_id, school_id, current_user.id)

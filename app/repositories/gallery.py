import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gallery import GalleryAlbum, GalleryPhoto


class GalleryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # Albums
    async def create_album(self, data: dict) -> GalleryAlbum:
        obj = GalleryAlbum(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_album_by_id(
        self, album_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[GalleryAlbum]:
        result = await self.db.execute(
            select(GalleryAlbum).where(
                and_(
                    GalleryAlbum.id == album_id,
                    GalleryAlbum.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_albums(self, school_id: uuid.UUID) -> list[GalleryAlbum]:
        result = await self.db.execute(
            select(GalleryAlbum)
            .where(GalleryAlbum.school_id == school_id)
            .order_by(GalleryAlbum.event_date.desc())
        )
        return list(result.scalars().all())

    async def update_album(self, album: GalleryAlbum, data: dict) -> GalleryAlbum:
        for key, value in data.items():
            setattr(album, key, value)
        await self.db.flush()
        await self.db.refresh(album)
        return album

    # Photos
    async def create_photo(self, data: dict) -> GalleryPhoto:
        obj = GalleryPhoto(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_photo_by_id(
        self, photo_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[GalleryPhoto]:
        result = await self.db.execute(
            select(GalleryPhoto).where(
                and_(
                    GalleryPhoto.id == photo_id,
                    GalleryPhoto.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_photos(self, album_id: uuid.UUID, school_id: uuid.UUID) -> list[GalleryPhoto]:
        result = await self.db.execute(
            select(GalleryPhoto)
            .where(
                and_(
                    GalleryPhoto.album_id == album_id,
                    GalleryPhoto.school_id == school_id,
                )
            )
            .order_by(GalleryPhoto.uploaded_at.desc())
        )
        return list(result.scalars().all())

    async def update_photo(self, photo: GalleryPhoto, data: dict) -> GalleryPhoto:
        for key, value in data.items():
            setattr(photo, key, value)
        await self.db.flush()
        await self.db.refresh(photo)
        return photo

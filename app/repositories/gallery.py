import uuid
from typing import Optional

from sqlalchemy import select, and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gallery import (
    GalleryAlbum,
    GalleryPhoto,
    GalleryPhotoComment,
    GalleryPhotoReaction,
)


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

    async def delete_album(self, album: GalleryAlbum) -> None:
        await self.db.delete(album)
        await self.db.flush()

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

    async def clear_featured_for_album_except(
        self, album_id: uuid.UUID, school_id: uuid.UUID, except_photo_id: uuid.UUID
    ) -> None:
        await self.db.execute(
            update(GalleryPhoto)
            .where(
                and_(
                    GalleryPhoto.album_id == album_id,
                    GalleryPhoto.school_id == school_id,
                    GalleryPhoto.id != except_photo_id,
                    GalleryPhoto.is_featured.is_(True),
                )
            )
            .values(is_featured=False)
        )
        await self.db.flush()

    # Reactions
    async def get_reaction(
        self, photo_id: uuid.UUID, user_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[GalleryPhotoReaction]:
        result = await self.db.execute(
            select(GalleryPhotoReaction).where(
                and_(
                    GalleryPhotoReaction.photo_id == photo_id,
                    GalleryPhotoReaction.reacted_by == user_id,
                    GalleryPhotoReaction.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def create_reaction(self, data: dict) -> GalleryPhotoReaction:
        obj = GalleryPhotoReaction(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update_reaction(
        self, reaction: GalleryPhotoReaction, data: dict
    ) -> GalleryPhotoReaction:
        for key, value in data.items():
            setattr(reaction, key, value)
        await self.db.flush()
        await self.db.refresh(reaction)
        return reaction

    async def delete_reaction(self, reaction: GalleryPhotoReaction) -> None:
        await self.db.delete(reaction)
        await self.db.flush()

    async def count_reactions(self, photo_id: uuid.UUID, school_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(GalleryPhotoReaction.id)).where(
                and_(
                    GalleryPhotoReaction.photo_id == photo_id,
                    GalleryPhotoReaction.school_id == school_id,
                )
            )
        )
        return int(result.scalar() or 0)

    # Comments
    async def create_comment(self, data: dict) -> GalleryPhotoComment:
        obj = GalleryPhotoComment(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def list_comments(
        self, photo_id: uuid.UUID, school_id: uuid.UUID
    ) -> list[GalleryPhotoComment]:
        result = await self.db.execute(
            select(GalleryPhotoComment)
            .where(
                and_(
                    GalleryPhotoComment.photo_id == photo_id,
                    GalleryPhotoComment.school_id == school_id,
                )
            )
            .order_by(GalleryPhotoComment.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_comment_by_id(
        self, comment_id: uuid.UUID, photo_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[GalleryPhotoComment]:
        result = await self.db.execute(
            select(GalleryPhotoComment).where(
                and_(
                    GalleryPhotoComment.id == comment_id,
                    GalleryPhotoComment.photo_id == photo_id,
                    GalleryPhotoComment.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def delete_comment(self, comment: GalleryPhotoComment) -> None:
        await self.db.delete(comment)
        await self.db.flush()

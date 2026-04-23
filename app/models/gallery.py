from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    String,
    Text,
    Date,
    DateTime,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Enum as SAEnum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.utils.enums import RoleEnum

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.school import School
    from app.models.academic_year import AcademicYear


class GalleryAlbum(BaseModel):
    __tablename__ = "gallery_albums"

    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_photo_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    creator: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[created_by], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )
    photos: Mapped[list["GalleryPhoto"]] = relationship(
        "GalleryPhoto", back_populates="album", lazy="select"
    )


class GalleryPhoto(BaseModel):
    __tablename__ = "gallery_photos"

    album_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gallery_albums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    photo_key: Mapped[str] = mapped_column(String(500), nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    album: Mapped["GalleryAlbum"] = relationship(
        "GalleryAlbum", foreign_keys=[album_id], back_populates="photos", lazy="select"
    )
    uploader: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[uploaded_by], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
    reactions: Mapped[list["GalleryPhotoReaction"]] = relationship(
        "GalleryPhotoReaction", back_populates="photo", lazy="select"
    )
    comments: Mapped[list["GalleryPhotoComment"]] = relationship(
        "GalleryPhotoComment", back_populates="photo", lazy="select"
    )


class GalleryPhotoReaction(BaseModel):
    __tablename__ = "gallery_photo_reactions"
    __table_args__ = (
        UniqueConstraint("photo_id", "reacted_by", name="uq_gallery_photo_reaction_user"),
    )

    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gallery_photos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reacted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reactor_role: Mapped[RoleEnum] = mapped_column(
        SAEnum(RoleEnum, name="roleenum", create_type=False),
        nullable=False,
    )
    reaction: Mapped[str] = mapped_column(String(20), nullable=False, default="LIKE")
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    photo: Mapped["GalleryPhoto"] = relationship(
        "GalleryPhoto", foreign_keys=[photo_id], back_populates="reactions", lazy="select"
    )
    reactor: Mapped["User"] = relationship(
        "User", foreign_keys=[reacted_by], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )


class GalleryPhotoComment(BaseModel):
    __tablename__ = "gallery_photo_comments"

    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gallery_photos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    commented_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    commenter_role: Mapped[RoleEnum] = mapped_column(
        SAEnum(RoleEnum, name="roleenum", create_type=False),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    photo: Mapped["GalleryPhoto"] = relationship(
        "GalleryPhoto", foreign_keys=[photo_id], back_populates="comments", lazy="select"
    )
    commenter: Mapped["User"] = relationship(
        "User", foreign_keys=[commented_by], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )

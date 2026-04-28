"""Backward-compatible base model exports for model imports.

Historically some models imported `BaseModel` from `app.models.base`.
The canonical implementation now lives in `app.db.base`.
This shim keeps older imports working and avoids runtime import errors.
"""

from app.db.base import Base, BaseModel, TimestampMixin, UUIDMixin

__all__ = ["Base", "BaseModel", "TimestampMixin", "UUIDMixin"]


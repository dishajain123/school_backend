import uuid
from typing import Optional
from pydantic import BaseModel


class PermissionResponse(BaseModel):
    id: uuid.UUID
    code: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    permissions: list[str] = []

    model_config = {"from_attributes": True}


class RolePermissionResponse(BaseModel):
    role_id: uuid.UUID
    permission_id: uuid.UUID

    model_config = {"from_attributes": True}
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SettingItem(BaseModel):
    key: str = Field(..., min_length=1)
    value: str


class SettingsUpdateRequest(BaseModel):
    items: list[SettingItem]


class SettingResponse(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    setting_key: str
    setting_value: str
    updated_by: Optional[uuid.UUID] = None
    updated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class SettingsListResponse(BaseModel):
    items: list[SettingResponse]
    total: int

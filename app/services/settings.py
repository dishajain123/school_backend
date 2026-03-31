import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ValidationException
from app.repositories.settings import SettingsRepository
from app.schemas.settings import SettingsUpdateRequest, SettingsListResponse, SettingResponse


class SettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SettingsRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def list_settings(self, current_user: CurrentUser) -> SettingsListResponse:
        school_id = self._ensure_school(current_user)
        items = await self.repo.list_for_school(school_id)
        return SettingsListResponse(
            items=[SettingResponse.model_validate(i) for i in items],
            total=len(items),
        )

    async def upsert_settings(
        self,
        payload: SettingsUpdateRequest,
        current_user: CurrentUser,
    ) -> SettingsListResponse:
        school_id = self._ensure_school(current_user)
        await self.repo.upsert_settings(
            school_id=school_id,
            items=[{"key": i.key, "value": i.value} for i in payload.items],
            updated_by=current_user.id,
        )
        await self.db.commit()
        return await self.list_settings(current_user)

    async def get(self, school_id: uuid.UUID, key: str) -> Optional[str]:
        setting = await self.repo.get_by_key(school_id, key)
        return setting.setting_value if setting else None

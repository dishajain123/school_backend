from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.settings import SettingsUpdateRequest, SettingsListResponse
from app.services.settings import SettingsService

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=SettingsListResponse)
async def list_settings(
    current_user: CurrentUser = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    return await SettingsService(db).list_settings(current_user)


@router.patch("", response_model=SettingsListResponse)
async def update_settings(
    payload: SettingsUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    return await SettingsService(db).upsert_settings(payload, current_user)

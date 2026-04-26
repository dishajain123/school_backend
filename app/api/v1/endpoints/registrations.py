from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.registration import RegistrationCreateRequest, RegistrationResponse
from app.services.registration import RegistrationService
from app.utils.enums import RegistrationSource

router = APIRouter(prefix="/registrations", tags=["Registrations"])


@router.post("/self", response_model=RegistrationResponse, status_code=201)
async def create_self_registration(
    payload: RegistrationCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = RegistrationService(db)
    user = await service.create_registration(payload, source=RegistrationSource.SELF_REGISTERED)
    return RegistrationResponse(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        school_id=user.school_id,
        status=user.status,
        registration_source=user.registration_source,
        created_at=user.created_at,
    )


@router.post("/admin", response_model=RegistrationResponse, status_code=201)
async def create_admin_registration(
    payload: RegistrationCreateRequest,
    _: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = RegistrationService(db)
    user = await service.create_registration(payload, source=RegistrationSource.ADMIN_CREATED)
    return RegistrationResponse(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        school_id=user.school_id,
        status=user.status,
        registration_source=user.registration_source,
        created_at=user.created_at,
    )

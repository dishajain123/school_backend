import uuid
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.behaviour import BehaviourCreate, BehaviourResponse, BehaviourListResponse
from app.services.behaviour import BehaviourService
from app.utils.enums import IncidentType

router = APIRouter(prefix="/behaviour", tags=["Behaviour"])


@router.post("", response_model=BehaviourResponse, status_code=201)
async def create_behaviour_log(
    payload: BehaviourCreate,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("behaviour_log:create")),
    db: AsyncSession = Depends(get_db),
):
    return await BehaviourService(db).create_log(
        payload, current_user, background_tasks
    )


@router.get("", response_model=BehaviourListResponse)
async def list_behaviour_logs(
    student_id: Optional[uuid.UUID] = Query(None),
    incident_type: Optional[IncidentType] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(require_permission("behaviour_log:read")),
    db: AsyncSession = Depends(get_db),
):
    return await BehaviourService(db).list_logs(
        student_id=student_id,
        incident_type=incident_type,
        standard_id=standard_id,
        section=section,
        current_user=current_user,
    )

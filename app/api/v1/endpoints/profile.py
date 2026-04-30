from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import ValidationException
from app.db.session import get_db
from app.repositories.parent import ParentRepository
from app.repositories.teacher import TeacherRepository
from app.services.student import StudentService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/profile", tags=["Profile"])


class ProfileEnvelope(BaseModel):
    role: str
    user: dict[str, Any]
    profile: Optional[dict[str, Any]] = None


@router.get("", response_model=ProfileEnvelope)
@router.get("/me", response_model=ProfileEnvelope)
async def get_profile(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.school_id:
        raise ValidationException("school_id is required")

    user_payload = {
        "id": str(current_user.id),
        "role": current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        "school_id": str(current_user.school_id),
        "full_name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone,
        "permissions": current_user.permissions,
    }

    if current_user.role == RoleEnum.STUDENT:
        student = await StudentService(db).get_my_student_profile(
            school_id=current_user.school_id,
            current_user=current_user,
        )
        return ProfileEnvelope(role="STUDENT", user=user_payload, profile=student.model_dump(mode="json"))

    if current_user.role == RoleEnum.TEACHER:
        teacher = await TeacherRepository(db).get_by_user_id(
            current_user.id,
            school_id=current_user.school_id,
        )
        if teacher:
            return ProfileEnvelope(
                role="TEACHER",
                user=user_payload,
                profile={
                    "id": str(teacher.id),
                    "employee_code": teacher.employee_code,
                    "academic_year_id": str(teacher.academic_year_id) if teacher.academic_year_id else None,
                    "join_date": teacher.join_date.isoformat() if teacher.join_date else None,
                    "specialization": teacher.specialization,
                },
            )
        return ProfileEnvelope(role="TEACHER", user=user_payload, profile=None)

    if current_user.role == RoleEnum.PARENT:
        parent = await ParentRepository(db).get_by_user_id(
            current_user.id,
            school_id=current_user.school_id,
        )
        if parent:
            return ProfileEnvelope(
                role="PARENT",
                user=user_payload,
                profile={
                    "id": str(parent.id),
                    "relation": parent.relation,
                    "occupation": parent.occupation,
                },
            )
        return ProfileEnvelope(role="PARENT", user=user_payload, profile=None)

    return ProfileEnvelope(
        role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        user=user_payload,
        profile=None,
    )

import re
import uuid
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ValidationException
from app.core.security import hash_password
from app.models.user import User
from app.models.registration_request import RegistrationRequest
from app.repositories.user import UserRepository
from app.schemas.registration import RegistrationCreateRequest
from app.utils.enums import RegistrationSource, RoleEnum, UserStatus

_PHONE_PATTERN = re.compile(r"^\+?[0-9]{10,15}$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegistrationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        cleaned = re.sub(r"[\s\-()]+", "", phone or "")
        return cleaned

    async def _assert_contact_uniqueness(self, email: Optional[str], phone: Optional[str]) -> None:
        if email:
            existing = await self.user_repo.get_by_email(email)
            if existing:
                raise ConflictException("A user with this email already exists")
        if phone:
            existing = await self.user_repo.get_by_phone(phone)
            if existing:
                raise ConflictException("A user with this phone number already exists")

    async def create_registration(
        self,
        payload: RegistrationCreateRequest,
        source: RegistrationSource,
    ) -> User:
        normalized_email = str(payload.email).lower().strip() if payload.email else None
        normalized_phone = self._normalize_phone(payload.phone) if payload.phone else None

        if not normalized_email and not normalized_phone:
            raise ValidationException("Email or phone is required")

        if normalized_phone and not _PHONE_PATTERN.match(normalized_phone):
            raise ValidationException("Invalid phone number format")

        await self._assert_contact_uniqueness(normalized_email, normalized_phone)

        user = await self.user_repo.create(
            {
                "full_name": payload.full_name.strip() if payload.full_name else None,
                "email": normalized_email,
                "phone": normalized_phone,
                "hashed_password": hash_password(payload.password),
                "role": payload.role,
                "school_id": payload.school_id,
                "status": UserStatus.PENDING_APPROVAL,
                "registration_source": source,
                "is_active": False,
                "submitted_data": payload.submitted_data,
            }
        )
        await self.db.flush()
        
        # Create immutable RegistrationRequest snapshot
        registration_request = RegistrationRequest(
            user_id=user.id,
            school_id=payload.school_id,
            role_requested=payload.role,
            registration_source=source,
            full_name=user.full_name or "",
            email=normalized_email,
            phone=normalized_phone,
            submitted_data=payload.submitted_data,
            has_duplicates=False,
            duplicate_details=None,
            data_complete=True,
            missing_fields=None,
            current_status=UserStatus.PENDING_APPROVAL,
        )
        self.db.add(registration_request)
        
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def validate_user_for_approval(self, user: User) -> tuple[list[dict], list[dict]]:
        issues: list[dict] = []
        duplicates: list[dict] = []

        if not user.full_name or not user.full_name.strip():
            issues.append({"field": "full_name", "message": "full_name is required"})

        if not user.school_id and user.role != RoleEnum.SUPERADMIN:
            issues.append({"field": "school_id", "message": "school_id is required"})

        if not user.email and not user.phone:
            issues.append({"field": "contact", "message": "email or phone is required"})
        elif user.email and not _EMAIL_PATTERN.match(user.email):
            issues.append({"field": "email", "message": "invalid email format"})

        if user.phone and not _PHONE_PATTERN.match(self._normalize_phone(user.phone)):
            issues.append({"field": "phone", "message": "invalid phone format"})

        if user.email:
            conflict_q = await self.db.execute(
                select(User.id)
                .where(and_(User.email == user.email, User.id != user.id))
                .limit(1)
            )
            conflict_id = conflict_q.scalar_one_or_none()
            if conflict_id:
                duplicates.append(
                    {
                        "type": "email",
                        "value": user.email,
                        "matched_user_id": str(conflict_id),
                    }
                )

        if user.phone:
            conflict_q = await self.db.execute(
                select(User.id)
                .where(and_(User.phone == user.phone, User.id != user.id))
                .limit(1)
            )
            conflict_id = conflict_q.scalar_one_or_none()
            if conflict_id:
                duplicates.append(
                    {
                        "type": "phone",
                        "value": user.phone,
                        "matched_user_id": str(conflict_id),
                    }
                )

        if user.full_name and user.school_id:
            full_name_norm = user.full_name.strip().lower()
            potential_q = await self.db.execute(
                select(User.id, User.full_name, User.role, User.email, User.phone)
                .where(
                    and_(
                        User.id != user.id,
                        User.school_id == user.school_id,
                        func.lower(func.trim(User.full_name)) == full_name_norm,
                        or_(
                            User.email.is_not(None),
                            User.phone.is_not(None),
                        ),
                    )
                )
                .limit(5)
            )
            for row in potential_q.all():
                duplicates.append(
                    {
                        "type": "basic_identity",
                        "matched_user_id": str(row.id),
                        "full_name": row.full_name,
                        "role": row.role.value if row.role else None,
                        "email": row.email,
                        "phone": row.phone,
                    }
                )

        return issues, duplicates

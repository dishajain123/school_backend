"""
Create a Staff Admin (STAFF_ADMIN) user for the web admin console.

Requires DEFAULT_SCHOOL_ID in .env (single-school).

Usage:
    python -m scripts.create_staff_admin --email admin@school.edu --password Secret123
    python -m scripts.create_staff_admin --email admin@school.edu --phone +911234567890 --password Secret123
"""
import argparse
import asyncio
import uuid
from typing import Optional

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.repositories.user import UserRepository
from app.core.security import hash_password
from app.utils.enums import RegistrationSource, RoleEnum, UserStatus


def _default_school_id() -> uuid.UUID:
    if not settings.DEFAULT_SCHOOL_ID:
        raise SystemExit(
            "DEFAULT_SCHOOL_ID must be set in the environment (single-school). "
            "Use the same UUID as your schools.id row."
        )
    return uuid.UUID(str(settings.DEFAULT_SCHOOL_ID).strip())


async def create_staff_admin(email: str, phone: Optional[str], password: str) -> None:
    school_id = _default_school_id()
    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        existing = await repo.get_by_email_or_phone(email, phone)
        if existing:
            existing.email = email.lower().strip()
            existing.phone = phone
            existing.hashed_password = hash_password(password)
            existing.role = RoleEnum.STAFF_ADMIN
            existing.school_id = school_id
            existing.is_active = True
            existing.status = UserStatus.ACTIVE
            existing.registration_source = RegistrationSource.ADMIN_CREATED
            await db.commit()
            await db.refresh(existing)
            print(f"Staff admin updated: {existing.id}")
            return

        user = await repo.create(
            {
                "email": email.lower().strip(),
                "phone": phone,
                "hashed_password": hash_password(password),
                "role": RoleEnum.STAFF_ADMIN,
                "school_id": school_id,
                "status": UserStatus.ACTIVE,
                "registration_source": RegistrationSource.ADMIN_CREATED,
                "is_active": True,
            }
        )
        await db.commit()
        await db.refresh(user)
        print(f"Staff admin created: {user.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Staff Admin user (web console)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--phone", required=False, default=None)
    args = parser.parse_args()

    asyncio.run(create_staff_admin(args.email, args.phone, args.password))


if __name__ == "__main__":
    main()

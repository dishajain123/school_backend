"""
Create a SUPERADMIN user.

Usage:
    python -m scripts.create_superadmin --email admin@example.com --password Secret123
    python -m scripts.create_superadmin --email admin@example.com --phone +911234567890 --password Secret123
"""
# FIX: The original file contained the entire script body twice (both the
# import block and the main() / create_superadmin() definitions). The duplicate
# second copy is removed here.
import argparse
import asyncio
from typing import Optional

from app.db.session import AsyncSessionLocal
from app.repositories.user import UserRepository
from app.core.security import hash_password
from app.utils.enums import RegistrationSource, RoleEnum, UserStatus


async def create_superadmin(email: str, phone: Optional[str], password: str) -> None:
    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        existing = await repo.get_by_email_or_phone(email, phone)
        if existing:
            # Repair/upgrade existing account into a valid Phase-1 superadmin login.
            existing.email = email.lower().strip()
            existing.phone = phone
            existing.hashed_password = hash_password(password)
            existing.role = RoleEnum.SUPERADMIN
            existing.school_id = None
            existing.is_active = True
            existing.status = UserStatus.ACTIVE
            existing.registration_source = RegistrationSource.ADMIN_CREATED
            await db.commit()
            await db.refresh(existing)
            print(f"Superadmin updated: {existing.id}")
            return

        user = await repo.create(
            {
                "email": email.lower().strip(),
                "phone": phone,
                "hashed_password": hash_password(password),
                "role": RoleEnum.SUPERADMIN,
                "school_id": None,
                "status": UserStatus.ACTIVE,
                "registration_source": RegistrationSource.ADMIN_CREATED,
                "is_active": True,
            }
        )
        await db.commit()
        await db.refresh(user)
        print(f"Superadmin created: {user.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create superadmin user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--phone", required=False, default=None)
    args = parser.parse_args()

    asyncio.run(create_superadmin(args.email, args.phone, args.password))


if __name__ == "__main__":
    main()

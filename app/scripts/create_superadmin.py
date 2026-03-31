import argparse
import asyncio
import uuid

from app.db.session import AsyncSessionLocal
from app.repositories.user import UserRepository
from app.core.security import hash_password
from app.utils.enums import RoleEnum


async def create_superadmin(email: str, phone: str | None, password: str) -> None:
    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        existing = await repo.get_by_email_or_phone(email, phone)
        if existing:
            raise ValueError("User with this email/phone already exists")

        user = await repo.create(
            {
                "email": email.lower().strip(),
                "phone": phone,
                "hashed_password": hash_password(password),
                "role": RoleEnum.SUPERADMIN,
                "school_id": None,
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

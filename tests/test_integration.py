"""
HTTP integration tests (FastAPI TestClient + real Postgres session).

Enable with:
  INTEGRATION_TESTS=1 pytest tests/test_integration.py -v

Requires DATABASE_URL (and other settings) from .env — use a disposable database.
External I/O is mocked where noted (MinIO bucket check at startup, gallery storage).
"""

from __future__ import annotations

import asyncio
import io
import os
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Set INTEGRATION_TESTS=1 and use a disposable Postgres DATABASE_URL.",
)


def _unwrap_json(r):
    """Many routes return the API success envelope."""
    data = r.json()
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        return r.status_code, data["data"]
    return r.status_code, data


def _access_token(login_response) -> str:
    data = login_response.json()
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        return data["data"]["access_token"]
    return data["access_token"]


async def _seed_integration_users() -> dict:
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.db.session import AsyncSessionLocal
    from app.models.academic_year import AcademicYear
    from app.models.permission import Permission
    from app.models.role import Role
    from app.models.role_permission import RolePermission
    from app.models.school import School
    from app.models.user import User
    from app.utils.enums import RegistrationSource, RoleEnum, UserStatus

    suffix = uuid.uuid4().hex[:8]
    # Avoid .local / reserved TLDs (Pydantic email-validator rejects them).
    principal_email = f"int_principal_{suffix}@example.com"
    student_email = f"int_student_{suffix}@example.com"
    password = "IntegrationTest1!"

    async with AsyncSessionLocal() as session:
        school = School(
            name=f"Integration School {suffix}",
            contact_email=f"school_{suffix}@example.com",
            is_active=True,
        )
        session.add(school)
        await session.flush()

        year = AcademicYear(
            name=f"Y{suffix[:4]}",
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() + timedelta(days=300),
            is_active=True,
            school_id=school.id,
        )
        session.add(year)
        await session.flush()

        principal = User(
            full_name="Integration Principal",
            email=principal_email,
            phone=None,
            hashed_password=hash_password(password),
            role=RoleEnum.PRINCIPAL,
            school_id=school.id,
            status=UserStatus.ACTIVE,
            registration_source=RegistrationSource.ADMIN_CREATED,
            is_active=True,
        )
        student = User(
            full_name="Integration Student",
            email=student_email,
            phone=None,
            hashed_password=hash_password(password),
            role=RoleEnum.STUDENT,
            school_id=school.id,
            status=UserStatus.ACTIVE,
            registration_source=RegistrationSource.ADMIN_CREATED,
            is_active=True,
        )
        session.add(principal)
        session.add(student)
        await session.flush()

        # Ensure principal can create gallery albums in this DB.
        role_row = await session.execute(
            select(Role.id).where(Role.name == RoleEnum.PRINCIPAL.value)
        )
        role_id = role_row.scalar_one_or_none()
        perm_row = await session.execute(
            select(Permission.id).where(Permission.code == "gallery:create")
        )
        perm_id = perm_row.scalar_one_or_none()
        if role_id and perm_id:
            existing = await session.execute(
                select(RolePermission.role_id).where(
                    RolePermission.role_id == role_id,
                    RolePermission.permission_id == perm_id,
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(
                    RolePermission(role_id=role_id, permission_id=perm_id)
                )

        await session.commit()

        return {
            "school_id": str(school.id),
            "year_id": str(year.id),
            "principal_email": principal_email,
            "student_email": student_email,
            "password": password,
            "principal_id": str(principal.id),
            "student_id": str(student.id),
        }


async def _dispose_engine_pool() -> None:
    """Drop pooled asyncpg connections so TestClient's thread loop can open fresh ones."""
    from app.db.session import engine

    await engine.dispose()


async def _seed_integration_users_then_dispose_pool() -> dict:
    ctx = await _seed_integration_users()
    await _dispose_engine_pool()
    return ctx


@pytest.fixture(scope="module")
def integration_ctx() -> dict:
    return asyncio.run(_seed_integration_users_then_dispose_pool())


@pytest.fixture(scope="module")
def client(integration_ctx: dict):  # noqa: ARG001 — seed DB before app lifespan touches it
    # Startup checks use the same DATABASE_URL as the seed; unrelated rows may exist locally.
    # Skip global NULL-school guard so tests only validate the routes under test.
    with patch("app.lifespan.ensure_buckets_exist", new_callable=AsyncMock), patch(
        "app.lifespan._assert_users_have_school_id", new_callable=AsyncMock
    ):
        from app.main import app

        with TestClient(app) as c:
            yield c


def test_login_then_me(client: TestClient, integration_ctx: dict):
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": integration_ctx["principal_email"],
            "password": integration_ctx["password"],
        },
    )
    assert login.status_code == 200, login.text
    token = _access_token(login)

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200, me.text
    status, payload = _unwrap_json(me)
    assert status == 200
    assert uuid.UUID(str(payload["id"])) == uuid.UUID(integration_ctx["principal_id"])


def test_users_requires_school_context(client: TestClient, integration_ctx: dict):
    from app.core.dependencies import CurrentUser, get_current_user
    from app.main import app
    from app.utils.enums import RoleEnum, UserStatus

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": integration_ctx["principal_email"],
            "password": integration_ctx["password"],
        },
    )
    assert login.status_code == 200
    token = _access_token(login)

    async def override_no_school() -> CurrentUser:
        return CurrentUser(
            id=uuid.UUID(integration_ctx["principal_id"]),
            role=RoleEnum.PRINCIPAL,
            school_id=None,
            parent_id=None,
            permissions=["user:manage", "document:manage"],
            status=UserStatus.ACTIVE,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = override_no_school
    try:
        r = client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_gallery_upload_valid_and_oversized(client: TestClient, integration_ctx: dict):
    from app.utils.constants import MAX_FILE_SIZE_BYTES

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": integration_ctx["principal_email"],
            "password": integration_ctx["password"],
        },
    )
    assert login.status_code == 200
    token = _access_token(login)

    album = client.post(
        "/api/v1/gallery/albums",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_name": "Integration Album",
            "event_date": str(date.today()),
            "description": "test",
            "academic_year_id": integration_ctx["year_id"],
        },
    )
    assert album.status_code == 201, album.text
    _, album_data = _unwrap_json(album)
    album_id = album_data["id"]

    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with patch(
        "app.services.gallery.minio_client.upload_file",
        lambda **kwargs: None,
    ), patch(
        "app.services.gallery.minio_client.generate_presigned_url",
        return_value="http://test/presigned",
    ):
        ok = client.post(
            f"/api/v1/gallery/albums/{album_id}/photos",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("tiny.png", io.BytesIO(tiny_png), "image/png")},
            data={"caption": "hi"},
        )
        assert ok.status_code == 201, ok.text

        huge = b"\x00" * (MAX_FILE_SIZE_BYTES + 1)
        bad = client.post(
            f"/api/v1/gallery/albums/{album_id}/photos",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("huge.png", io.BytesIO(huge), "image/png")},
            data={},
        )
        assert bad.status_code == 422


def test_permission_denied_settings_list(client: TestClient, integration_ctx: dict):
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": integration_ctx["student_email"],
            "password": integration_ctx["password"],
        },
    )
    assert login.status_code == 200
    token = _access_token(login)

    r = client.get(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403

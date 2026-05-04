"""Focused checks for auth context, RBAC resolution, and upload limits."""

import io
import uuid
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from app.core.dependencies import (
    CurrentUser,
    hydrate_current_user_from_access_payload,
    get_current_user_from_access_token,
)
from app.core.exceptions import (
    ForbiddenException,
    InternalServerException,
    UnauthorizedException,
    ValidationException,
)
from app.services.auth import AuthService
from app.services.document import DocumentService
from app.utils.constants import MAX_FILE_SIZE_BYTES
from app.utils.enums import DocumentType, RoleEnum, UserStatus


def _user_row_result(
    status: UserStatus,
    is_active: bool,
    school_id: Optional[uuid.UUID],
    role: RoleEnum = RoleEnum.STUDENT,
):
    r = MagicMock()
    r.one_or_none.return_value = (status, is_active, school_id, role)
    return r


@pytest.mark.asyncio
async def test_hydrate_user_without_school_no_token_school_no_default_raises():
    """Missing DB school_id requires DEFAULT_SCHOOL_ID; JWT school is not tenant context."""
    uid = uuid.uuid4()
    payload = {
        "sub": str(uid),
        "role": RoleEnum.STUDENT.value,
        "permissions": [],
    }
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_user_row_result(UserStatus.ACTIVE, True, None))

    with patch("app.core.dependencies.settings") as mock_settings:
        mock_settings.DEFAULT_SCHOOL_ID = None
        with pytest.raises(UnauthorizedException, match="School context is missing"):
            await hydrate_current_user_from_access_payload(payload, db)


@pytest.mark.asyncio
async def test_hydrate_ignores_jwt_school_when_db_null_without_default():
    """JWT school_id must not establish tenant; without DB school + DEFAULT → 401."""
    uid = uuid.uuid4()
    payload = {
        "sub": str(uid),
        "role": RoleEnum.STUDENT.value,
        "permissions": [],
        "school_id": str(uuid.uuid4()),
    }
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_user_row_result(UserStatus.ACTIVE, True, None))
    with patch("app.core.dependencies.settings") as mock_settings:
        mock_settings.DEFAULT_SCHOOL_ID = None
        with pytest.raises(UnauthorizedException, match="School context is missing"):
            await hydrate_current_user_from_access_payload(payload, db)


@pytest.mark.asyncio
async def test_hydrate_rejects_jwt_school_mismatch_when_using_default_school():
    """When DB school is null and DEFAULT applies, a stale JWT school claim → 403."""
    uid = uuid.uuid4()
    default_sid = uuid.uuid4()
    payload = {
        "sub": str(uid),
        "role": RoleEnum.STUDENT.value,
        "permissions": [],
        "school_id": str(uuid.uuid4()),
    }
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_user_row_result(UserStatus.ACTIVE, True, None))
    with patch("app.core.dependencies.settings") as mock_settings:
        mock_settings.DEFAULT_SCHOOL_ID = str(default_sid)
        with pytest.raises(ForbiddenException, match="Token school claim"):
            await hydrate_current_user_from_access_payload(payload, db)


@pytest.mark.asyncio
async def test_hydrate_user_without_school_uses_default_school_id_when_configured():
    uid = uuid.uuid4()
    default_sid = uuid.uuid4()
    payload = {
        "sub": str(uid),
        "role": RoleEnum.STUDENT.value,
        "permissions": [],
    }
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_user_row_result(UserStatus.ACTIVE, True, None))

    with patch("app.core.dependencies.settings") as mock_settings:
        mock_settings.DEFAULT_SCHOOL_ID = str(default_sid)
        user = await hydrate_current_user_from_access_payload(payload, db)

    assert user.school_id == default_sid


@pytest.mark.asyncio
async def test_hydrate_token_school_mismatch_for_user_with_school_raises():
    uid = uuid.uuid4()
    user_school = uuid.uuid4()
    other = uuid.uuid4()
    payload = {
        "sub": str(uid),
        "role": RoleEnum.TEACHER.value,
        "permissions": [],
        "school_id": str(other),
    }
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_user_row_result(UserStatus.ACTIVE, True, user_school, RoleEnum.TEACHER)
    )

    with pytest.raises(ForbiddenException, match="Token school claim"):
        await hydrate_current_user_from_access_payload(payload, db)


@pytest.mark.asyncio
async def test_hydrate_rejects_token_role_mismatch_with_db():
    uid = uuid.uuid4()
    school = uuid.uuid4()
    payload = {
        "sub": str(uid),
        "role": RoleEnum.STUDENT.value,
        "permissions": [],
    }
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_user_row_result(UserStatus.ACTIVE, True, school, RoleEnum.TEACHER)
    )
    with pytest.raises(ForbiddenException, match="Token role claim"):
        await hydrate_current_user_from_access_payload(payload, db)


@pytest.mark.asyncio
async def test_get_permissions_for_role_returns_codes_from_db():
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["student:read", "attendance:mark"]
    mock_db.execute = AsyncMock(return_value=result)

    svc = AuthService(mock_db)
    perms = await svc._get_permissions_for_role(RoleEnum.TEACHER)

    assert perms == ["student:read", "attendance:mark"]
    mock_db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_get_permissions_for_role_db_error_raises_internal():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=RuntimeError("db down"))

    svc = AuthService(mock_db)
    with pytest.raises(InternalServerException, match="Unable to resolve role permissions"):
        await svc._get_permissions_for_role(RoleEnum.PRINCIPAL)


@pytest.mark.asyncio
async def test_invalid_access_token_rejected_before_blocklist_query():
    db = AsyncMock()
    with pytest.raises(UnauthorizedException, match="Invalid or expired token"):
        await get_current_user_from_access_token("not-a-valid-jwt", db)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_document_rejects_file_over_max_size():
    db = AsyncMock()
    svc = DocumentService(db)

    current_user = CurrentUser(
        id=uuid.uuid4(),
        role=RoleEnum.PRINCIPAL,
        school_id=uuid.uuid4(),
        parent_id=None,
        permissions=[],
    )
    large = b"x" * (MAX_FILE_SIZE_BYTES + 1)
    upload = UploadFile(filename="huge.pdf", file=io.BytesIO(large))

    with (
        patch.object(DocumentService, "_assert_student_scope", new_callable=AsyncMock),
        patch("app.services.document.get_active_year", new_callable=AsyncMock) as mock_active_year,
    ):
        mock_active_year.return_value = MagicMock(id=uuid.uuid4())
        with pytest.raises(ValidationException, match="exceeds maximum"):
            await svc.upload_document(
                student_id=uuid.uuid4(),
                document_type=DocumentType.BONAFIDE,
                file=upload,
                note=None,
                current_user=current_user,
            )

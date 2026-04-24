import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.exceptions import GoneException
from app.integrations.minio_client import minio_client, local_file_path

router = APIRouter(prefix="/files", tags=["Files"])


@router.get("/local/{bucket}/{file_key:path}")
async def get_local_file(
    bucket: str,
    file_key: str,
    exp: int = Query(..., description="Signed URL expiry (unix epoch seconds)"),
    sig: str = Query(..., description="Signed URL signature"),
):
    normalized_key = file_key.lstrip("/")
    if not minio_client.validate_local_file_signature(
        bucket=bucket,
        key=normalized_key,
        expires_at=exp,
        signature=sig,
    ):
        raise HTTPException(status_code=403, detail="Invalid or expired file URL")

    path = local_file_path(bucket=bucket, key=normalized_key).resolve()
    bucket_root = local_file_path(bucket=bucket, key="").resolve()

    # Guard against path traversal.
    try:
        path.relative_to(bucket_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file key")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=str(path),
        media_type=media_type or "application/octet-stream",
        filename=Path(normalized_key).name,
    )


@router.get("/{bucket}/{file_key:path}", deprecated=True)
async def get_local_file_deprecated(
    bucket: str,
    file_key: str,
):
    raise GoneException(
        detail=(
            "Deprecated API: /files/{bucket}/{file_key} is no longer available. "
            "Use signed URLs returned by domain APIs."
        )
    )

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.integrations.minio_client import local_file_path

router = APIRouter(prefix="/files", tags=["Files"])


@router.get("/{bucket}/{file_key:path}")
async def get_local_file(bucket: str, file_key: str):
    path = local_file_path(bucket=bucket, key=file_key)
    root = (Path(__file__).resolve().parents[4] / "local_storage").resolve()
    resolved = path.resolve()

    if root not in resolved.parents and resolved != root:
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(resolved)


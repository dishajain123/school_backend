import io
import socket
import warnings
import hmac
import hashlib
import base64
from pathlib import Path
from urllib.parse import quote
from typing import Optional
from datetime import datetime, timezone

warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*",
)

from minio import Minio
from minio.error import S3Error
from app.core.config import settings, BASE_DIR
from app.core.logging import get_logger
from app.utils.constants import MINIO_BUCKETS, PRESIGNED_URL_EXPIRY
from datetime import timedelta

logger = get_logger(__name__)

_client: Optional[Minio] = None
_LOCAL_STORAGE_ROOT = BASE_DIR / "local_storage"


def _endpoint_host_port() -> tuple[str, int]:
    endpoint = settings.MINIO_ENDPOINT.strip()
    if "://" in endpoint:
        endpoint = endpoint.split("://", 1)[1]
    host, _, port = endpoint.partition(":")
    return host, int(port or 9000)


def _is_minio_reachable(timeout: float = 0.5) -> bool:
    host, port = _endpoint_host_port()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=not settings.DEBUG,
        )
    return _client


def _use_local_storage() -> bool:
    return (not settings.MINIO_ENABLED) or (not _is_minio_reachable())


def _local_file_path(bucket: str, key: str) -> Path:
    normalized = key.lstrip("/")
    return _LOCAL_STORAGE_ROOT / bucket / normalized


def local_file_path(bucket: str, key: str) -> Path:
    return _local_file_path(bucket=bucket, key=key)


async def ensure_buckets_exist() -> None:
    if not settings.MINIO_ENABLED:
        logger.info("MinIO is disabled; skipping bucket verification")
        return
    if not _is_minio_reachable():
        logger.warning(
            f"MinIO is not reachable at {settings.MINIO_ENDPOINT}; skipping bucket verification"
        )
        return
    client = get_minio_client()
    for bucket in MINIO_BUCKETS:
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                logger.info(f"Created MinIO bucket: {bucket}")
            else:
                logger.debug(f"MinIO bucket already exists: {bucket}")
        except S3Error as e:
            logger.error(f"Failed to ensure bucket '{bucket}': {e}")
            raise


def upload_file(
    bucket: str,
    key: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    if _use_local_storage():
        path = _local_file_path(bucket=bucket, key=key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file_bytes)
        logger.debug(f"Stored file locally: {path}")
        return key

    try:
        client = get_minio_client()
        client.put_object(
            bucket_name=bucket,
            object_name=key,
            data=io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type,
        )
        logger.debug(f"Uploaded file to MinIO: {bucket}/{key}")
        return key
    except Exception as e:
        logger.warning(
            f"MinIO upload failed for {bucket}/{key}; falling back to local storage: {e}"
        )
        path = _local_file_path(bucket=bucket, key=key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file_bytes)
        logger.debug(f"Stored file locally after MinIO failure: {path}")
        return key


def generate_presigned_url(
    bucket: str,
    key: str,
    expiry: int = PRESIGNED_URL_EXPIRY,
) -> str:
    if _use_local_storage():
        return generate_local_signed_file_url(bucket=bucket, key=key, expiry=expiry)

    try:
        client = get_minio_client()
        url = client.presigned_get_object(
            bucket_name=bucket,
            object_name=key,
            expires=timedelta(seconds=expiry),
        )
        return url
    except Exception as e:
        logger.warning(
            f"Failed to generate MinIO presigned URL for {bucket}/{key}; using local URL: {e}"
        )
        return generate_local_signed_file_url(bucket=bucket, key=key, expiry=expiry)


def delete_file(bucket: str, key: str) -> None:
    if _use_local_storage():
        path = _local_file_path(bucket=bucket, key=key)
        if path.exists():
            path.unlink()
        return

    client = get_minio_client()
    try:
        client.remove_object(bucket_name=bucket, object_name=key)
        logger.debug(f"Deleted file from MinIO: {bucket}/{key}")
    except S3Error as e:
        logger.error(f"MinIO delete failed for {bucket}/{key}: {e}")
        raise


def file_exists(bucket: str, key: str) -> bool:
    if _use_local_storage():
        return _local_file_path(bucket=bucket, key=key).exists()

    client = get_minio_client()
    try:
        client.stat_object(bucket_name=bucket, object_name=key)
        return True
    except S3Error:
        return False


def _sign_local_file_payload(bucket: str, key: str, expires_at: int) -> str:
    payload = f"{bucket}:{key}:{expires_at}"
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def generate_local_signed_file_url(
    bucket: str,
    key: str,
    expiry: int = PRESIGNED_URL_EXPIRY,
) -> str:
    normalized_key = key.lstrip("/")
    expires_at = int(datetime.now(timezone.utc).timestamp()) + int(expiry)
    signature = _sign_local_file_payload(bucket, normalized_key, expires_at)
    encoded_key = quote(normalized_key, safe="/")
    return (
        f"{settings.BACKEND_BASE_URL}/api/v1/files/local/{quote(bucket)}/{encoded_key}"
        f"?exp={expires_at}&sig={signature}"
    )


def validate_local_file_signature(
    bucket: str,
    key: str,
    expires_at: int,
    signature: str,
) -> bool:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if expires_at < now_ts:
        return False

    expected = _sign_local_file_payload(bucket, key.lstrip("/"), expires_at)
    return hmac.compare_digest(expected, signature)


class _MinioClientFacade:
    def get_minio_client(self) -> Minio:
        return get_minio_client()

    async def ensure_buckets_exist(self) -> None:
        await ensure_buckets_exist()

    def upload_file(
        self,
        bucket: str,
        key: str,
        file_bytes: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        return upload_file(bucket=bucket, key=key, file_bytes=file_bytes, content_type=content_type)

    def generate_presigned_url(
        self,
        bucket: str,
        key: str,
        expiry: int = PRESIGNED_URL_EXPIRY,
    ) -> str:
        return generate_presigned_url(bucket=bucket, key=key, expiry=expiry)

    def generate_local_signed_file_url(
        self,
        bucket: str,
        key: str,
        expiry: int = PRESIGNED_URL_EXPIRY,
    ) -> str:
        return generate_local_signed_file_url(bucket=bucket, key=key, expiry=expiry)

    def validate_local_file_signature(
        self,
        bucket: str,
        key: str,
        expires_at: int,
        signature: str,
    ) -> bool:
        return validate_local_file_signature(
            bucket=bucket,
            key=key,
            expires_at=expires_at,
            signature=signature,
        )

    def delete_file(self, bucket: str, key: str) -> None:
        delete_file(bucket=bucket, key=key)

    def file_exists(self, bucket: str, key: str) -> bool:
        return file_exists(bucket=bucket, key=key)


# Backward-compatible facade used by services
minio_client = _MinioClientFacade()

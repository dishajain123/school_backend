import io
from typing import Optional
from minio import Minio
from minio.error import S3Error
from app.core.config import settings
from app.core.logging import get_logger
from app.utils.constants import MINIO_BUCKETS, PRESIGNED_URL_EXPIRY
from datetime import timedelta

logger = get_logger(__name__)

_client: Optional[Minio] = None


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


async def ensure_buckets_exist() -> None:
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
    client = get_minio_client()
    try:
        client.put_object(
            bucket_name=bucket,
            object_name=key,
            data=io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type,
        )
        logger.debug(f"Uploaded file to MinIO: {bucket}/{key}")
        return key
    except S3Error as e:
        logger.error(f"MinIO upload failed for {bucket}/{key}: {e}")
        raise


def generate_presigned_url(
    bucket: str,
    key: str,
    expiry: int = PRESIGNED_URL_EXPIRY,
) -> str:
    client = get_minio_client()
    try:
        url = client.presigned_get_object(
            bucket_name=bucket,
            object_name=key,
            expires=timedelta(seconds=expiry),
        )
        return url
    except S3Error as e:
        logger.error(f"Failed to generate presigned URL for {bucket}/{key}: {e}")
        raise


def delete_file(bucket: str, key: str) -> None:
    client = get_minio_client()
    try:
        client.remove_object(bucket_name=bucket, object_name=key)
        logger.debug(f"Deleted file from MinIO: {bucket}/{key}")
    except S3Error as e:
        logger.error(f"MinIO delete failed for {bucket}/{key}: {e}")
        raise


def file_exists(bucket: str, key: str) -> bool:
    client = get_minio_client()
    try:
        client.stat_object(bucket_name=bucket, object_name=key)
        return True
    except S3Error:
        return False
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.init_db import init_db
from app.integrations.minio_client import ensure_buckets_exist
from app.core.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up SMS backend...")
    await init_db()
    logger.info("Database initialized successfully")
    try:
        await ensure_buckets_exist()
        logger.info("MinIO buckets verified")
    except Exception as e:
        logger.warning(f"MinIO bucket setup failed (non-fatal): {e}")
    yield
    logger.info("Shutting down SMS backend...")
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI
from app.db.init_db import init_db
from app.integrations.minio_client import ensure_buckets_exist
from app.core.logging import get_logger
from app.core.api_usage_tracker import (
    DEPRECATED_APIS,
    UNUSED_CANDIDATE_APIS,
    api_usage_tracker,
)
from app.db.session import AsyncSessionLocal
from app.repositories.otp_store import OtpStoreRepository
from app.repositories.jti_blocklist import JtiBlocklistRepository
from app.repositories.notification import NotificationRepository

logger = get_logger(__name__)


async def _cleanup_loop(stop_event: asyncio.Event) -> None:
    last_otp = 0.0
    last_jti = 0.0
    last_notif = 0.0
    otp_interval = 60 * 60  # hourly
    jti_interval = 6 * 60 * 60  # every 6 hours
    notif_interval = 24 * 60 * 60  # daily

    while not stop_event.is_set():
        now = asyncio.get_event_loop().time()
        try:
            async with AsyncSessionLocal() as db:
                if now - last_otp >= otp_interval:
                    deleted = await OtpStoreRepository(db).purge_expired()
                    if deleted:
                        logger.info(f"Purged {deleted} expired OTPs")
                    last_otp = now

                if now - last_jti >= jti_interval:
                    deleted = await JtiBlocklistRepository(db).purge_expired()
                    if deleted:
                        logger.info(f"Purged {deleted} expired JTIs")
                    last_jti = now

                if now - last_notif >= notif_interval:
                    deleted = await NotificationRepository(db).purge_old(cutoff_days=90)
                    if deleted:
                        logger.info(f"Purged {deleted} old notifications")
                    last_notif = now
        except Exception as e:
            logger.warning(f"Cleanup job failed: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up SMS backend...")
    logger.info(
        "API usage tracking enabled: deprecated=%s unused_candidates=%s",
        len(DEPRECATED_APIS),
        len(UNUSED_CANDIDATE_APIS),
    )
    await init_db()
    logger.info("Database initialized successfully")
    try:
        await ensure_buckets_exist()
        logger.info("MinIO buckets verified")
    except Exception as e:
        logger.warning(f"MinIO bucket setup failed (non-fatal): {e}")
    stop_event = asyncio.Event()
    cleanup_task = asyncio.create_task(_cleanup_loop(stop_event))
    yield
    stop_event.set()
    try:
        await cleanup_task
    except Exception:
        pass
    api_usage_tracker.log_runtime_summary()
    logger.info("Shutting down SMS backend...")

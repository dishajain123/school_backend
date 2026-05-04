from contextlib import asynccontextmanager
import asyncio
import uuid
from typing import Optional

from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.db.init_db import init_db
from app.integrations.minio_client import ensure_buckets_exist
from app.core.logging import get_logger
from app.core.api_usage_tracker import (
    DEPRECATED_APIS,
    UNUSED_CANDIDATE_APIS,
    api_usage_tracker,
)

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.school import School
from app.models.user import User
from app.repositories.otp_store import OtpStoreRepository
from app.repositories.jti_blocklist import JtiBlocklistRepository
from app.repositories.notification import NotificationRepository

logger = get_logger(__name__)


async def _assert_users_have_school_id() -> None:
    """Ensure users.school_id is set: optional startup backfill, then strict check."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count()).select_from(User).where(User.school_id.is_(None))
        )
        n = int(result.scalar_one())
        if n == 0:
            return

        backfill_school_id: Optional[uuid.UUID] = None
        if settings.DEFAULT_SCHOOL_ID:
            backfill_school_id = uuid.UUID(str(settings.DEFAULT_SCHOOL_ID).strip())
        elif settings.is_development_environment:
            school_rows = await db.execute(select(School.id))
            ids = list(school_rows.scalars().all())
            if len(ids) == 1:
                backfill_school_id = ids[0]
                logger.warning(
                    "Development: assigning NULL users.school_id to the only school row %s.",
                    backfill_school_id,
                )

        if backfill_school_id is not None:
            try:
                await db.execute(
                    update(User)
                    .where(User.school_id.is_(None))
                    .values(school_id=backfill_school_id)
                )
                await db.commit()
            except IntegrityError as e:
                await db.rollback()
                raise RuntimeError(
                    "Backfill of users.school_id failed (invalid DEFAULT_SCHOOL_ID or FK). "
                    "Ensure DEFAULT_SCHOOL_ID matches an existing schools.id row."
                ) from e
            result = await db.execute(
                select(func.count()).select_from(User).where(User.school_id.is_(None))
            )
            n = int(result.scalar_one())
            if n == 0:
                return

    msg = (
        f"{n} user(s) have NULL school_id. Set DEFAULT_SCHOOL_ID in .env to your schools.id "
        "UUID, or use ENVIRONMENT=local with exactly one school row for auto backfill. "
        "For production, run the Alembic migration that backfills school_id before NOT NULL."
    )
    if settings.DEBUG and settings.is_development_environment:
        logger.warning(
            "%s Startup continues because DEBUG is enabled in a development environment.",
            msg,
        )
    else:
        logger.error(msg)
        raise RuntimeError(msg)


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


def _assert_debug_not_enabled_in_production() -> None:
    """Settings load already validates DEBUG+ENVIRONMENT; log explicit production posture."""
    if settings.ENVIRONMENT == "production" and settings.DEBUG:
        raise RuntimeError(
            "Invalid configuration: DEBUG cannot be enabled in production. "
            "This is blocked at settings validation; if you see this, configuration loading is broken."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _assert_debug_not_enabled_in_production()
    logger.info("Starting up SMS backend (environment=%s)...", settings.ENVIRONMENT)
    logger.info(
        "API usage tracking enabled: deprecated=%s unused_candidates=%s",
        len(DEPRECATED_APIS),
        len(UNUSED_CANDIDATE_APIS),
    )
    await init_db()
    logger.info("Database initialized successfully")
    await _assert_users_have_school_id()
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

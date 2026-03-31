from app.db.session import engine
from app.db.base import Base
from app.core.logging import get_logger

logger = get_logger(__name__)


async def init_db() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
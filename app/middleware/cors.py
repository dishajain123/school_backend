from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def setup_cors(app: FastAPI) -> None:
    if settings.ALLOWED_ORIGINS == "*":
        logger.warning("CORS is set to '*'. For production, set explicit origins.")
        origins: list[str] = []
    else:
        origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Request-ID",
            "Accept",
            "Origin",
        ],
    )

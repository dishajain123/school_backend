from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def setup_cors(app: FastAPI) -> None:
    allow_origin_regex: Optional[str] = None

    if settings.ALLOWED_ORIGINS == "*":
        # Dev-friendly default for Flutter Web / local frontend ports.
        # Examples: http://localhost:64617, http://192.168.1.25:55921
        logger.warning(
            "ALLOWED_ORIGINS='*' detected. Allowing localhost + private-network origins."
        )
        origins = [
            "http://localhost",
            "http://127.0.0.1",
            "http://host.docker.internal",
        ]
        allow_origin_regex = (
            r"^https?://("
            r"localhost|127\.0\.0\.1|host\.docker\.internal|"
            r"(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3})|"
            r"(?:192\.168\.\d{1,3}\.\d{1,3})|"
            r"(?:172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})"
            r")(:\d+)?$"
        )
    else:
        origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
        has_localhost_origin = any(
            o.startswith("http://localhost")
            or o.startswith("https://localhost")
            or o.startswith("http://127.0.0.1")
            or o.startswith("https://127.0.0.1")
            for o in origins
        )
        if has_localhost_origin:
            # Keep explicit origins, but also support dynamic dev ports
            # used by Flutter Web / Vite / React dev servers.
            allow_origin_regex = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=allow_origin_regex,
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

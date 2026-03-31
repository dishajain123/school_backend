from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections import defaultdict
from datetime import datetime, timezone
import time
from app.core.logging import get_logger

logger = get_logger(__name__)

_request_counts: dict[str, list[float]] = defaultdict(list)

AUTH_ENDPOINTS = ["/api/v1/auth/login", "/api/v1/auth/forgot-password", "/api/v1/auth/verify-otp"]
AUTH_RATE_LIMIT = 10
GENERAL_RATE_LIMIT = 60
WINDOW_SECONDS = 60


def _is_rate_limited(key: str, limit: int) -> bool:
    now = time.time()
    window_start = now - WINDOW_SECONDS

    _request_counts[key] = [t for t in _request_counts[key] if t > window_start]

    if len(_request_counts[key]) >= limit:
        return True

    _request_counts[key].append(now)
    return False


def setup_rate_limiter(app: FastAPI) -> None:
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        is_auth = any(path.startswith(ep) for ep in AUTH_ENDPOINTS)
        limit = AUTH_RATE_LIMIT if is_auth else GENERAL_RATE_LIMIT
        key = f"{client_ip}:{path if is_auth else 'general'}"

        if _is_rate_limited(key, limit):
            logger.warning(f"Rate limit exceeded for IP: {client_ip}, path: {path}")
            return JSONResponse(
                status_code=429,
                content={"error": "RATE_LIMIT_EXCEEDED", "detail": "Too many requests. Please try again later."},
            )

        return await call_next(request)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections import defaultdict
import time
from app.core.logging import get_logger
from app.core.response import error_response

logger = get_logger(__name__)

_request_counts: dict[str, list[float]] = defaultdict(list)

RATE_LIMIT_OVERRIDES: dict[str, int] = {
    "/api/v1/auth/login": 5,
    "/api/v1/auth/refresh": 15,
    "/api/v1/auth/forgot-password": 5,
    "/api/v1/auth/verify-otp": 8,
    "/api/v1/auth/reset-password": 5,
}
PUBLIC_ENDPOINTS = {
    "/",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/verify-otp",
    "/api/v1/auth/reset-password",
}
PUBLIC_RATE_LIMIT = 30
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
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", "unknown")
        trace_id = getattr(request.state, "trace_id", None) or request.headers.get("X-Trace-ID", request_id)

        if path in RATE_LIMIT_OVERRIDES:
            limit = RATE_LIMIT_OVERRIDES[path]
            key_scope = path
        elif path in PUBLIC_ENDPOINTS:
            limit = PUBLIC_RATE_LIMIT
            key_scope = path
        else:
            limit = GENERAL_RATE_LIMIT
            key_scope = "general"
        key = f"{client_ip}:{key_scope}"

        if _is_rate_limited(key, limit):
            logger.warning(
                "rate_limit_exceeded ip=%s path=%s key_scope=%s limit=%s window_seconds=%s request_id=%s trace_id=%s",
                client_ip,
                path,
                key_scope,
                limit,
                WINDOW_SECONDS,
                request_id,
                trace_id,
            )
            return JSONResponse(
                status_code=429,
                content=error_response(
                    message="Too many requests. Please try again later.",
                    code="RATE_LIMIT_EXCEEDED",
                    details={"path": path, "limit": limit, "window_seconds": WINDOW_SECONDS},
                    request_id=request_id,
                ),
            )

        return await call_next(request)

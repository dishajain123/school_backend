from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.api_usage_tracker import api_usage_tracker
from app.core.logging import get_logger
from app.core.security import decode_token, extract_bearer_token

logger = get_logger(__name__)


def _extract_auth_context(request: Request) -> tuple[Optional[str], Optional[str]]:
    auth_header = request.headers.get("Authorization")
    token = extract_bearer_token(auth_header)
    if not token:
        return None, None
    try:
        payload = decode_token(token)
    except Exception:
        return None, None
    role = payload.get("role")
    user_id = payload.get("sub")
    return (str(role) if role else None, str(user_id) if user_id else None)


class ApiUsageLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        started = perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()
        role, user_id = _extract_auth_context(request)
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID")
        trace_id = request.headers.get("X-Trace-ID") or request_id
        request.state.user_role = role
        request.state.user_id = user_id
        request.state.trace_id = trace_id

        response = await call_next(request)

        duration_ms = round((perf_counter() - started) * 1000, 2)
        method = request.method.upper()
        path = request.url.path

        logger.info(
            "api_request method=%s endpoint=%s timestamp=%s role=%s user_id=%s request_id=%s trace_id=%s status=%s latency_ms=%s",
            method,
            path,
            timestamp,
            role or "unknown",
            user_id or "anonymous",
            request_id or "unknown",
            trace_id or "unknown",
            response.status_code,
            duration_ms,
        )
        api_usage_tracker.record_request(method=method, path=path, status_code=response.status_code)

        deprecated = api_usage_tracker.match_deprecated(method, path)
        if deprecated:
            count = api_usage_tracker.record_deprecated_hit(deprecated)
            logger.warning(
                "deprecated_api_used method=%s endpoint=%s hits=%s migration_hint=%s",
                method,
                deprecated.template,
                count,
                deprecated.migration_hint,
            )

        unused_candidate = api_usage_tracker.match_unused_candidate(method, path)
        if unused_candidate:
            count = api_usage_tracker.record_unused_candidate_hit(unused_candidate)
            logger.warning(
                "unused_candidate_api_hit method=%s endpoint=%s hits=%s status=actively used migration_hint=%s",
                method,
                unused_candidate.template,
                count,
                unused_candidate.migration_hint,
            )

        return response

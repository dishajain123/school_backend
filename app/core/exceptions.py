from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import uuid

from app.core.response import error_response
from app.core.logging import get_logger

logger = get_logger(__name__)


class AppException(HTTPException):
    def __init__(self, status_code: int, detail: str, error_code: str = None):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


class NotFoundException(AppException):
    def __init__(self, resource: str = "Resource", detail: str = None):
        message = detail if detail is not None else f"{resource} not found"
        super().__init__(status_code=404, detail=message, error_code="NOT_FOUND")


class ForbiddenException(AppException):
    def __init__(self, detail: str = "Access denied"):
        super().__init__(status_code=403, detail=detail, error_code="FORBIDDEN")


class UnauthorizedException(AppException):
    def __init__(self, detail: str = "Not authenticated"):
        super().__init__(status_code=401, detail=detail, error_code="UNAUTHORIZED")


class ConflictException(AppException):
    def __init__(self, detail: str = "Resource already exists"):
        super().__init__(status_code=409, detail=detail, error_code="CONFLICT")


class GoneException(AppException):
    def __init__(self, detail: str = "This API has been removed"):
        super().__init__(status_code=410, detail=detail, error_code="GONE")


class ValidationException(AppException):
    def __init__(self, detail: str = "Validation failed"):
        super().__init__(status_code=422, detail=detail, error_code="VALIDATION_ERROR")


class MisconfigurationException(AppException):
    """Deployment invariant violated (e.g. single-school count)."""

    def __init__(self, detail: str):
        super().__init__(status_code=503, detail=detail, error_code="MISCONFIGURED")


class InternalServerException(AppException):
    """Unexpected server-side failure (e.g. RBAC query); never mask as empty data."""

    def __init__(self, detail: str = "An internal error occurred"):
        super().__init__(status_code=500, detail=detail, error_code="INTERNAL_ERROR")


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", str(uuid.uuid4()))
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("X-Trace-ID", request_id)
    user_id = getattr(request.state, "user_id", None)
    logger.warning(
        "app_exception method=%s path=%s status=%s code=%s detail=%s request_id=%s trace_id=%s user_id=%s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.error_code or "ERROR",
        str(exc.detail),
        request_id,
        trace_id,
        user_id or "anonymous",
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            message=str(exc.detail),
            code=exc.error_code or "ERROR",
            details=exc.detail,
            request_id=request_id,
        ),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    # Extract a single human-readable message so Flutter error_interceptor
    # always receives `detail` as a plain string, never a list.
    first = errors[0] if errors else {}
    msg: str = first.get("msg") or "Validation failed"
    # Strip the "Value error, " prefix Pydantic v2 adds
    if msg.lower().startswith("value error, "):
        msg = msg[len("value error, "):]
    field_loc = " -> ".join(str(p) for p in first.get("loc", []) if p != "body")
    human = f"{field_loc}: {msg}" if field_loc else msg

    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", str(uuid.uuid4()))
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("X-Trace-ID", request_id)
    user_id = getattr(request.state, "user_id", None)
    logger.warning(
        "validation_exception method=%s path=%s status=422 detail=%s request_id=%s trace_id=%s user_id=%s",
        request.method,
        request.url.path,
        human,
        request_id,
        trace_id,
        user_id or "anonymous",
    )
    return JSONResponse(
        status_code=422,
        content=error_response(
            message=human,
            code="VALIDATION_ERROR",
            details=errors,
            request_id=request_id,
        ),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", str(uuid.uuid4()))
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("X-Trace-ID", request_id)
    user_id = getattr(request.state, "user_id", None)
    logger.warning(
        "http_exception method=%s path=%s status=%s detail=%s request_id=%s trace_id=%s user_id=%s",
        request.method,
        request.url.path,
        exc.status_code,
        detail,
        request_id,
        trace_id,
        user_id or "anonymous",
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            message=detail,
            code="HTTP_ERROR",
            details=exc.detail,
            request_id=request_id,
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Last-resort handler for bugs / unexpected failures.
    More specific handlers (AppException, validation, HTTPException) win via MRO.
    """
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", str(uuid.uuid4()))
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("X-Trace-ID", request_id)
    user_id = getattr(request.state, "user_id", None)
    logger.error(
        "unhandled_exception method=%s path=%s request_id=%s trace_id=%s user_id=%s",
        request.method,
        request.url.path,
        request_id,
        trace_id,
        user_id or "anonymous",
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"},
    )

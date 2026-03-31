from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import uuid


class AppException(HTTPException):
    def __init__(self, status_code: int, detail: str, error_code: str = None):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


class NotFoundException(AppException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(status_code=404, detail=f"{resource} not found", error_code="NOT_FOUND")


class ForbiddenException(AppException):
    def __init__(self, detail: str = "Access denied"):
        super().__init__(status_code=403, detail=detail, error_code="FORBIDDEN")


class UnauthorizedException(AppException):
    def __init__(self, detail: str = "Not authenticated"):
        super().__init__(status_code=401, detail=detail, error_code="UNAUTHORIZED")


class ConflictException(AppException):
    def __init__(self, detail: str = "Resource already exists"):
        super().__init__(status_code=409, detail=detail, error_code="CONFLICT")


class ValidationException(AppException):
    def __init__(self, detail: str = "Validation failed"):
        super().__init__(status_code=422, detail=detail, error_code="VALIDATION_ERROR")


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code or "ERROR",
            "detail": exc.detail,
            "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "VALIDATION_ERROR",
            "detail": exc.errors(),
            "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
        },
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTP_ERROR",
            "detail": exc.detail,
            "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
        },
    )
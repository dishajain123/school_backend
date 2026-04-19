from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.lifespan import lifespan
from app.middleware.cors import setup_cors
from app.middleware.rate_limiter import setup_rate_limiter
from app.middleware.request_id import RequestIdMiddleware
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    validation_exception_handler,
    http_exception_handler,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="School Management System",
        version="2.2.0",
        lifespan=lifespan,
    )

    setup_rate_limiter(app)
    app.add_middleware(RequestIdMiddleware)
    # Keep CORS outermost so even error responses include CORS headers.
    setup_cors(app)

    # Register exception handlers so all errors return consistent JSON
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    @app.get("/")
    async def health_check():
        return {"status": "ok"}

    from app.api.v1.router import api_router
    app.include_router(api_router, prefix="/api/v1")

    from app.ws.chat_router import ws_router
    app.include_router(ws_router, prefix="/api/v1")

    return app


app = create_app()

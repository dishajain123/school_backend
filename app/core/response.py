import json
from typing import Any, Optional

from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from starlette.responses import Response


def success_response(data: Any, message: str = "OK") -> dict[str, Any]:
    return {
        "success": True,
        "data": data,
        "message": message,
        "error": None,
    }


def error_response(
    *,
    message: str,
    code: str,
    details: Any = None,
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "data": None,
        "message": message,
        "error": {
            "code": code,
            "details": details,
            "request_id": request_id,
        },
    }


class ApiEnvelopeRoute(APIRoute):
    """Wrap successful JSON responses in a consistent API envelope."""

    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request) -> Response:
            response: Response = await original_route_handler(request)

            # Keep empty/no-content responses untouched.
            if response.status_code == 204:
                return response

            media_type = (response.media_type or "").lower()
            if "application/json" not in media_type:
                return response

            body_bytes = response.body or b""
            if not body_bytes:
                return response

            try:
                payload = json.loads(body_bytes)
            except json.JSONDecodeError:
                return response

            # Avoid double-wrapping.
            if (
                isinstance(payload, dict)
                and {"success", "data", "message", "error"}.issubset(payload.keys())
            ):
                return response

            wrapped = success_response(payload)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return JSONResponse(
                status_code=response.status_code,
                content=wrapped,
                headers=headers,
                background=response.background,
            )

        return custom_route_handler

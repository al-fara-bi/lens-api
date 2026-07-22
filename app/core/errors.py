"""Domain exceptions and the global error handlers.

Every error leaves the API in one shape, so clients never have to branch on
which layer failed:

    {"error": {"code": "...", "message": "...", "details": [...]}, "request_id": "..."}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Starlette raises *its* HTTPException for unmatched routes and wrong methods.
# fastapi.HTTPException is a subclass, and handler lookup walks the raised
# exception's MRO — so registering the subclass would miss every 404 and 405,
# leaving them with Starlette's default {"detail": ...} shape instead of ours.
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors that map to a deliberate HTTP response."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "Internal server error"

    def __init__(self, message: str | None = None, details: Any = None) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


class RateLimitExceeded(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limit_exceeded"
    message = "Too many requests. Please try again later."

    def __init__(self, retry_after: int) -> None:
        super().__init__(details={"retry_after_seconds": retry_after})
        self.retry_after = retry_after


class MailDeliveryError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "mail_delivery_failed"
    message = "Your message was saved but the notification email could not be sent."


class StorageError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "storage_unavailable"
    message = "Could not store the request. Please try again later."


def _envelope(request: Request, code: str, message: str, details: Any = None) -> dict:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    body["request_id"] = getattr(request.state, "request_id", None)
    return body


def register_exception_handlers(app: FastAPI, *, debug: bool) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("AppError %s: %s", exc.code, exc.message)
        headers = {}
        if isinstance(exc, RateLimitExceeded):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, exc.code, exc.message, exc.details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Flatten pydantic's output into something a form can map onto fields.
        details = [
            {
                "field": ".".join(str(p) for p in err["loc"] if p != "body"),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=jsonable_encoder(
                _envelope(request, "validation_error", "Invalid input data.", details)
            ),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, "http_error", str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Full traceback goes to app.log; the client gets nothing exploitable.
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                request,
                "internal_error",
                str(exc) if debug else "Internal server error",
            ),
        )

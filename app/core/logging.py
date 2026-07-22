"""File-based logging.

The task requires every request to be written to a file, so two sinks are set up:

* ``app.log``      — application events (AI fallbacks, mail failures, errors)
* ``requests.log`` — one JSON line per HTTP request, for machine-readable analysis

Both rotate at 5 MB to keep a long-running container from filling the disk.
"""

import json
import logging
import time
import uuid
from logging.handlers import RotatingFileHandler

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings
from app.core.net import get_client_ip

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

# These emit one DEBUG line per SQL statement and per socket operation. At
# DEBUG level they bury our own messages and inflate the log file, so they are
# pinned regardless of the app's level.
NOISY_LOGGERS = ("aiosqlite", "sqlalchemy.engine", "sqlalchemy.pool", "httpcore", "httpx")

request_logger = logging.getLogger("app.requests")


def setup_logging(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if settings.debug else logging.INFO

    app_handler = RotatingFileHandler(
        settings.app_log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    app_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s")
    )

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)-8s %(name)s | %(message)s"))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [app_handler, console]

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Request log is JSON-only and must not leak into app.log.
    req_handler = RotatingFileHandler(
        settings.request_log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    req_handler.setFormatter(logging.Formatter("%(message)s"))
    request_logger.setLevel(logging.INFO)
    request_logger.handlers = [req_handler]
    request_logger.propagate = False


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Writes one JSON line per request and tags it with a correlation id."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # Log the failed request before the exception handler turns it into a 500.
            self._write(request, request_id, 500, started)
            raise

        self._write(request, request_id, status_code, started)
        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _write(request: Request, request_id: str, status_code: int, started: float) -> None:
        request_logger.info(
            json.dumps(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.url.query),
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "client_ip": get_client_ip(request),
                    "user_agent": request.headers.get("user-agent", ""),
                },
                ensure_ascii=False,
            )
        )

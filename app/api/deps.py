"""FastAPI dependencies.

Long-lived collaborators (AI chain, mail, rate limiter) are built once during
startup and stored on ``app.state``; these functions just hand them to routes.
Building them per request would re-read config and re-create HTTP clients on
every call.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import RateLimitExceeded
from app.core.net import get_client_ip
from app.repositories.ratelimit_repo import RateLimiter
from app.services.contact_service import ContactService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_contact_service(request: Request) -> ContactService:
    return request.app.state.contact_service


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_request_ip(request: Request) -> str:
    return get_client_ip(request)


async def enforce_rate_limit(request: Request) -> None:
    """Route dependency: rejects with 429 before the handler body runs.

    Applied per route rather than as middleware so that reads (`/api/health`,
    `/api/metrics`) stay unthrottled while writes are protected.
    """
    limiter: RateLimiter = request.app.state.rate_limiter
    allowed, retry_after = await limiter.check(get_client_ip(request))
    if not allowed:
        raise RateLimitExceeded(retry_after=retry_after)


ContactServiceDep = Annotated[ContactService, Depends(get_contact_service)]
ClientIPDep = Annotated[str, Depends(get_request_ip)]

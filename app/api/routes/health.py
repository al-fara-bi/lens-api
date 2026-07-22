"""GET /api/health — liveness and dependency status.

Also serves as the container health check, which is why it stays cheap: it
verifies the database answers and reports configuration state, but never calls
out to the AI providers or the SMTP server. A health check that makes paid API
calls every 30 seconds is its own outage.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SettingsDep
from app.core.database import get_session
from app.schemas.common import HealthResponse, ServiceCheck

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description="Reports database connectivity plus AI and SMTP configuration state.",
)
async def health(
    request: Request,
    settings: SettingsDep,
    session: AsyncSession = Depends(get_session),
) -> HealthResponse:
    checks: list[ServiceCheck] = []

    try:
        await session.execute(text("SELECT 1"))
        checks.append(ServiceCheck(name="database", healthy=True))
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        checks.append(ServiceCheck(name="database", healthy=False, detail=str(exc)))

    ai_service = request.app.state.ai_service
    configured = ai_service.available_providers
    checks.append(
        ServiceCheck(
            name="ai",
            healthy=bool(configured),
            detail=(
                f"providers: {', '.join(configured)}"
                if configured
                else "no provider configured; submissions will use fallback analysis"
            ),
        )
    )

    checks.append(
        ServiceCheck(
            name="smtp",
            healthy=settings.mail_configured,
            detail=None if settings.mail_configured else "SMTP not configured; emails are skipped",
        )
    )

    # Only the database is fatal — the other two have documented degraded modes.
    db_ok = next(c.healthy for c in checks if c.name == "database")
    all_ok = all(c.healthy for c in checks)

    return HealthResponse(
        status="ok" if all_ok else ("degraded" if db_ok else "unhealthy"),
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
        checks=checks,
    )

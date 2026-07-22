"""GET /api/metrics — submission statistics.

Computed from the submissions table on request rather than kept in a counter
file. A counter is a second copy of the truth: it drifts on every failed write,
every rollback, and every manual row edit, and nothing reconciles it.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.repositories.submission_repo import SubmissionRepository
from app.schemas.common import MetricsResponse

router = APIRouter(tags=["system"])


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Submission statistics",
    description=(
        "Aggregated counts by sentiment, category, and AI provider, plus the share "
        "of submissions that were analysed without falling back."
    ),
)
async def metrics(session: AsyncSession = Depends(get_session)) -> MetricsResponse:
    stats = await SubmissionRepository(session).metrics()
    return MetricsResponse(**stats, generated_at=datetime.now(timezone.utc))

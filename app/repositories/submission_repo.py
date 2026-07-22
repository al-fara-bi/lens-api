"""Persistence and aggregation for contact submissions."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import AIStatus, Submission
from app.schemas.contact import AIAnalysis, ContactRequest


class SubmissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, payload: ContactRequest, analysis: AIAnalysis, client_ip: str | None
    ) -> Submission:
        submission = Submission(
            name=payload.name,
            phone=payload.phone,
            email=str(payload.email),
            comment=payload.comment,
            client_ip=client_ip,
            sentiment=analysis.sentiment.value if analysis.status == AIStatus.OK else None,
            category=analysis.category.value if analysis.status == AIStatus.OK else None,
            ai_reply=analysis.suggested_reply or None,
            ai_provider=analysis.provider,
            ai_status=analysis.status.value,
            ai_error=analysis.error,
        )
        self.session.add(submission)
        await self.session.commit()
        await self.session.refresh(submission)
        return submission

    async def count_all(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Submission))
        return int(result.scalar_one())

    async def count_since(self, since: datetime) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Submission).where(Submission.created_at >= since)
        )
        return int(result.scalar_one())

    async def _group_count(self, column) -> dict[str, int]:
        result = await self.session.execute(
            select(column, func.count()).where(column.is_not(None)).group_by(column)
        )
        return {str(key): int(count) for key, count in result.all()}

    async def metrics(self) -> dict:
        total = await self.count_all()
        last_24h = await self.count_since(datetime.now(timezone.utc) - timedelta(hours=24))

        analysed = await self.session.execute(
            select(func.count())
            .select_from(Submission)
            .where(Submission.ai_status == AIStatus.OK.value)
        )
        analysed_count = int(analysed.scalar_one())

        return {
            "total_submissions": total,
            "submissions_last_24h": last_24h,
            "by_sentiment": await self._group_count(Submission.sentiment),
            "by_category": await self._group_count(Submission.category),
            "by_ai_provider": await self._group_count(Submission.ai_provider),
            "ai_success_rate": round(analysed_count / total, 4) if total else 0.0,
        }

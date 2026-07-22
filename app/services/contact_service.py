"""Orchestrates one contact submission end to end.

    validation (schema) -> AI analysis -> persistence -> email -> response

The AI call runs inline rather than in a background task. That is a deliberate
trade: the visitor waits for it (bounded by AI_TIMEOUT_SECONDS), but the owner's
notification email arrives already classified and with a draft reply, which is
the point of the feature. Moving it to a background task would return faster and
send a bare notification — worth revisiting only if the form gets chatty enough
for latency to matter.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import StorageError
from app.repositories.submission_repo import SubmissionRepository
from app.schemas.contact import ContactAcceptedData, ContactRequest
from app.services.ai.service import AIService
from app.services.mail_service import MailService

logger = logging.getLogger(__name__)


class ContactService:
    def __init__(self, ai_service: AIService, mail_service: MailService) -> None:
        self.ai_service = ai_service
        self.mail_service = mail_service

    async def submit(
        self, payload: ContactRequest, client_ip: str | None, session: AsyncSession
    ) -> ContactAcceptedData:
        # 1. Analyse. Never raises: an unreachable AI degrades to neutral values.
        analysis = await self.ai_service.analyze(payload)

        # 2. Persist. This one *does* raise — if we cannot store the request,
        #    telling the visitor it was received would be a lie.
        repo = SubmissionRepository(session)
        try:
            submission = await repo.create(payload, analysis, client_ip)
        except Exception as exc:
            logger.exception("Failed to store submission from %s", payload.email)
            raise StorageError() from exc

        # 3. Notify. Already-stored, so failures are reported, not raised.
        email_sent = await self.mail_service.send_submission_emails(submission, analysis)
        if not email_sent:
            logger.error(
                "Submission %s stored but email delivery failed or was skipped", submission.id
            )

        return ContactAcceptedData(
            submission_id=submission.id,
            created_at=submission.created_at,
            sentiment=analysis.sentiment if analysis.status.value == "ok" else None,
            category=analysis.category if analysis.status.value == "ok" else None,
            ai_status=analysis.status,
            email_sent=email_sent,
        )

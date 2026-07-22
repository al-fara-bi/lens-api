"""Email delivery over SMTP.

Two messages per submission, as required: a notification to the site owner and a
confirmation copy to the sender. They are sent concurrently — sequential sends
would double the caller's wait for no benefit.

Delivery failure never propagates. By the time we get here the submission is
already stored, so raising would tell the visitor their message was lost when it
was not. The failure is logged and surfaced as ``email_sent: false`` instead.
"""

import asyncio
import logging
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import Settings
from app.models.submission import Submission
from app.schemas.contact import AIAnalysis

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


class MailService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            # Autoescape is what stops a visitor's comment from injecting markup
            # into the HTML email the owner opens.
            autoescape=select_autoescape(["html", "xml"]),
            enable_async=True,
        )

    # ---------- public API ----------

    async def send_submission_emails(
        self, submission: Submission, analysis: AIAnalysis
    ) -> bool:
        """Send both messages. Returns True only if both were accepted."""
        if not self.settings.mail_configured:
            logger.warning("SMTP is not configured; skipping emails for %s", submission.id)
            return False

        results = await asyncio.gather(
            self._send_owner_notification(submission, analysis),
            self._send_user_confirmation(submission, analysis),
            return_exceptions=True,
        )

        ok = True
        for label, result in zip(("owner", "user"), results, strict=True):
            if isinstance(result, Exception):
                logger.error("Failed to send %s email for %s: %s", label, submission.id, result)
                ok = False
            elif result is False:
                ok = False
        return ok

    # ---------- individual messages ----------

    async def _send_owner_notification(
        self, submission: Submission, analysis: AIAnalysis
    ) -> bool:
        subject = f"New contact request from {submission.name}"
        if analysis.category:
            subject = f"[{analysis.category.value}] {subject}"

        html = await self.env.get_template("owner_notification.html").render_async(
            submission=submission, analysis=analysis
        )
        return await self._send(
            to=self.settings.owner_email,
            subject=subject,
            html=html,
            reply_to=submission.email,
        )

    async def _send_user_confirmation(
        self, submission: Submission, analysis: AIAnalysis
    ) -> bool:
        html = await self.env.get_template("user_confirmation.html").render_async(
            submission=submission, analysis=analysis
        )
        return await self._send(
            to=submission.email,
            subject="We received your message",
            html=html,
        )

    # ---------- transport ----------

    async def _send(
        self, *, to: str, subject: str, html: str, reply_to: str | None = None
    ) -> bool:
        message = EmailMessage()
        message["From"] = f"{self.settings.mail_from_name} <{self.settings.mail_from}>"
        message["To"] = to
        message["Subject"] = subject
        if reply_to:
            # Lets the owner hit Reply and answer the visitor directly.
            message["Reply-To"] = reply_to

        message.set_content("This message requires an HTML-capable email client.")
        message.add_alternative(html, subtype="html")

        await aiosmtplib.send(
            message,
            hostname=self.settings.smtp_host,
            port=self.settings.smtp_port,
            username=self.settings.smtp_user or None,
            password=self.settings.smtp_password or None,
            start_tls=self.settings.smtp_use_tls,
            timeout=10,
        )
        logger.info("Sent %r to %s", subject, to)
        return True

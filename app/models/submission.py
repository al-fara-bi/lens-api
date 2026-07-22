"""Contact-form submission and its AI analysis."""

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.db_types import UTCDateTime


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Category(StrEnum):
    JOB = "job"
    COLLABORATION = "collaboration"
    SUPPORT = "support"
    SPAM = "spam"
    OTHER = "other"


class AIStatus(StrEnum):
    OK = "ok"
    FALLBACK = "fallback"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)

    client_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_utcnow, nullable=False
    )

    # AI fields stay nullable on purpose: when every provider is unreachable the
    # submission is still stored and the emails still go out. `ai_status` records
    # which of the two paths was taken.
    sentiment: Mapped[str | None] = mapped_column(String(16))
    category: Mapped[str | None] = mapped_column(String(32))
    ai_reply: Mapped[str | None] = mapped_column(Text)
    ai_provider: Mapped[str | None] = mapped_column(String(32))
    ai_status: Mapped[str] = mapped_column(String(16), default=AIStatus.FALLBACK, nullable=False)
    ai_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_submissions_created_at", "created_at"),
        Index("ix_submissions_email", "email"),
    )

    def __repr__(self) -> str:
        return f"<Submission {self.id} {self.email} {self.ai_status}>"

"""Provider-agnostic contract for the AI layer.

One call does three jobs — sentiment, request classification, and a draft reply —
because they share the same context. Three separate calls would triple latency
and cost for no gain in quality.

The JSON schema below is handed to each provider's structured-output feature, so
the model is constrained to a valid shape instead of being asked politely and
parsed hopefully.
"""

import json
import logging
from typing import Protocol

from app.models.submission import AIStatus, Category, Sentiment
from app.schemas.contact import AIAnalysis, ContactRequest

logger = logging.getLogger(__name__)

ANALYSIS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {
            "type": "string",
            "enum": [s.value for s in Sentiment],
            "description": "Emotional tone of the message",
        },
        "category": {
            "type": "string",
            "enum": [c.value for c in Category],
            "description": (
                "job: hiring or job offer; collaboration: partnership or project proposal; "
                "support: question or problem; spam: advertising or nonsense; other: anything else"
            ),
        },
        "suggested_reply": {
            "type": "string",
            "description": (
                "A courteous 2-4 sentence draft reply addressed to the sender, "
                "written in the same language as their message."
            ),
        },
    },
    "required": ["sentiment", "category", "suggested_reply"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You analyse messages submitted through a software developer's contact form.\n"
    "For each message determine the sender's sentiment, classify what they want, "
    "and draft a short reply the developer could send back.\n"
    "Reply in the same language the sender used. Be professional and concise. "
    "Never invent commitments, prices, or deadlines on the developer's behalf."
)


def build_user_prompt(payload: ContactRequest) -> str:
    return (
        f"Sender name: {payload.name}\n"
        f"Sender email: {payload.email}\n"
        f"Message:\n\"\"\"\n{payload.comment}\n\"\"\""
    )


class AIAnalyzer(Protocol):
    """What every provider implementation must offer."""

    name: str

    def is_configured(self) -> bool:
        """False when the API key is missing, so the chain can skip it."""
        ...

    async def analyze(self, payload: ContactRequest) -> AIAnalysis:
        """Return a completed analysis or raise; the chain handles failures."""
        ...


def parse_analysis(raw: str, provider: str) -> AIAnalysis:
    """Turn a provider's JSON string into a validated AIAnalysis.

    Unknown enum values are coerced to safe defaults rather than raising: a model
    that answers "very positive" should not cost us the whole analysis.
    """
    data = json.loads(raw)

    try:
        sentiment = Sentiment(str(data.get("sentiment", "")).lower())
    except ValueError:
        logger.warning("%s returned unknown sentiment %r", provider, data.get("sentiment"))
        sentiment = Sentiment.NEUTRAL

    try:
        category = Category(str(data.get("category", "")).lower())
    except ValueError:
        logger.warning("%s returned unknown category %r", provider, data.get("category"))
        category = Category.OTHER

    return AIAnalysis(
        sentiment=sentiment,
        category=category,
        suggested_reply=str(data.get("suggested_reply", "")).strip(),
        provider=provider,
        status=AIStatus.OK,
    )


def fallback_analysis(error: str) -> AIAnalysis:
    """Used when no provider could answer.

    Neutral values, empty draft, and the reason recorded — the submission is
    still stored and the emails still go out.
    """
    return AIAnalysis(
        sentiment=Sentiment.NEUTRAL,
        category=Category.OTHER,
        suggested_reply="",
        provider=None,
        status=AIStatus.FALLBACK,
        error=error[:500],
    )

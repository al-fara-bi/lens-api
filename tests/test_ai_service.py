"""AI provider chain: the three degradation levels, tested without network calls.

Fake analyzers stand in for real providers so the suite is deterministic, free,
and does not depend on anyone's API key.
"""

import asyncio

import pytest

from app.models.submission import AIStatus, Category, Sentiment
from app.schemas.contact import AIAnalysis, ContactRequest
from app.services.ai.base import parse_analysis
from app.services.ai.service import AIService

PAYLOAD = ContactRequest(
    name="Ivan Petrov",
    phone="+79991234567",
    email="ivan@example.com",
    comment="Hello, I would like to hire you for a backend project.",
)


class WorkingAnalyzer:
    def __init__(self, name: str = "working") -> None:
        self.name = name
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    async def analyze(self, payload: ContactRequest) -> AIAnalysis:
        self.calls += 1
        return AIAnalysis(
            sentiment=Sentiment.POSITIVE,
            category=Category.JOB,
            suggested_reply="Thank you for reaching out.",
            provider=self.name,
            status=AIStatus.OK,
        )


class FailingAnalyzer:
    def __init__(self, name: str = "failing") -> None:
        self.name = name
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    async def analyze(self, payload: ContactRequest) -> AIAnalysis:
        self.calls += 1
        raise RuntimeError("provider is down")


class HangingAnalyzer:
    name = "hanging"

    def is_configured(self) -> bool:
        return True

    async def analyze(self, payload: ContactRequest) -> AIAnalysis:
        await asyncio.sleep(30)
        raise AssertionError("should have been cancelled by the timeout")


class UnconfiguredAnalyzer:
    name = "unconfigured"

    def __init__(self) -> None:
        self.calls = 0

    def is_configured(self) -> bool:
        return False

    async def analyze(self, payload: ContactRequest) -> AIAnalysis:
        self.calls += 1
        raise AssertionError("must not be called when unconfigured")


async def test_primary_provider_is_used_when_healthy() -> None:
    primary, secondary = WorkingAnalyzer("primary"), WorkingAnalyzer("secondary")
    service = AIService([primary, secondary], timeout=1.0)

    result = await service.analyze(PAYLOAD)

    assert result.status == AIStatus.OK
    assert result.provider == "primary"
    assert secondary.calls == 0, "fallback must not be called when the primary succeeds"


async def test_falls_through_to_secondary_provider() -> None:
    primary, secondary = FailingAnalyzer("primary"), WorkingAnalyzer("secondary")
    service = AIService([primary, secondary], timeout=1.0)

    result = await service.analyze(PAYLOAD)

    assert result.status == AIStatus.OK
    assert result.provider == "secondary"
    assert primary.calls == 1


async def test_all_providers_failing_degrades_to_neutral_analysis() -> None:
    service = AIService([FailingAnalyzer("a"), FailingAnalyzer("b")], timeout=1.0)

    result = await service.analyze(PAYLOAD)

    assert result.status == AIStatus.FALLBACK
    assert result.sentiment == Sentiment.NEUTRAL
    assert result.category == Category.OTHER
    assert result.provider is None
    # The reason is recorded so the failure is diagnosable after the fact.
    assert "a:" in result.error and "b:" in result.error


async def test_empty_chain_degrades_instead_of_raising() -> None:
    result = await AIService([], timeout=1.0).analyze(PAYLOAD)

    assert result.status == AIStatus.FALLBACK
    assert result.error == "no AI provider configured"


async def test_unconfigured_provider_is_skipped() -> None:
    unconfigured, working = UnconfiguredAnalyzer(), WorkingAnalyzer("working")
    service = AIService([unconfigured, working], timeout=1.0)

    result = await service.analyze(PAYLOAD)

    assert result.provider == "working"
    assert unconfigured.calls == 0


async def test_hanging_provider_times_out_and_falls_through() -> None:
    """A stalled primary must not hold the caller for its full timeout twice."""
    service = AIService([HangingAnalyzer(), WorkingAnalyzer("secondary")], timeout=0.2)

    result = await asyncio.wait_for(service.analyze(PAYLOAD), timeout=3.0)

    assert result.status == AIStatus.OK
    assert result.provider == "secondary"


# ---------- response parsing ----------


def test_parse_analysis_accepts_valid_payload() -> None:
    raw = '{"sentiment": "negative", "category": "support", "suggested_reply": "Sorry!"}'

    result = parse_analysis(raw, "test")

    assert result.sentiment == Sentiment.NEGATIVE
    assert result.category == Category.SUPPORT
    assert result.status == AIStatus.OK


def test_parse_analysis_coerces_unknown_enum_values() -> None:
    """A model answering off-schema should cost the label, not the whole analysis."""
    raw = '{"sentiment": "extremely positive", "category": "invoice", "suggested_reply": "Hi"}'

    result = parse_analysis(raw, "test")

    assert result.sentiment == Sentiment.NEUTRAL
    assert result.category == Category.OTHER
    assert result.suggested_reply == "Hi"


def test_parse_analysis_rejects_malformed_json() -> None:
    with pytest.raises(ValueError):
        parse_analysis("not json at all", "test")

"""Runs the configured providers in order and degrades gracefully.

Three outcomes, in decreasing order of quality:

1. The primary provider answers            -> full analysis, ai_status = ok
2. The primary fails, a fallback answers   -> full analysis, ai_status = ok, switch logged
3. Every provider fails                    -> neutral defaults, ai_status = fallback

Only the third is required by the task ("the service keeps working when the AI is
unavailable"). The second exists because a provider outage is far more likely than
both providers being down at once, and losing the analysis to a single 503 would
be a waste.

The per-provider timeout matters as much as the chain itself: without it, a
hanging primary would make the caller wait for its full timeout *and then* the
fallback's, turning a resilience feature into a worse experience than having none.
"""

import asyncio
import logging
import time

from app.core.config import Settings
from app.schemas.contact import AIAnalysis, ContactRequest
from app.services.ai.base import AIAnalyzer, fallback_analysis

logger = logging.getLogger(__name__)

# Provider SDKs raise exceptions carrying the whole HTTP error body. A single
# Gemini 429 is ~2 KB of quota JSON, logged once per attempt — enough repeated
# failures and the log file is mostly boilerplate. The leading part identifies
# the problem; the rest is documentation links.
MAX_PROVIDER_ERROR_CHARS = 300


def _short(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= MAX_PROVIDER_ERROR_CHARS else text[:MAX_PROVIDER_ERROR_CHARS] + " …"


class AIService:
    def __init__(self, providers: list[AIAnalyzer], timeout: float) -> None:
        self.providers = providers
        self.timeout = timeout

    @property
    def available_providers(self) -> list[str]:
        return [p.name for p in self.providers if p.is_configured()]

    async def analyze(self, payload: ContactRequest) -> AIAnalysis:
        errors: list[str] = []

        for provider in self.providers:
            if not provider.is_configured():
                logger.debug("Skipping %s: no API key configured", provider.name)
                continue

            started = time.perf_counter()
            try:
                analysis = await asyncio.wait_for(
                    provider.analyze(payload), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                elapsed = time.perf_counter() - started
                logger.warning("%s timed out after %.1fs", provider.name, elapsed)
                errors.append(f"{provider.name}: timeout after {self.timeout}s")
                continue
            except Exception as exc:  # noqa: BLE001 - any provider failure falls through
                reason = _short(exc)
                logger.warning("%s failed: %s", provider.name, reason)
                errors.append(f"{provider.name}: {reason}")
                continue

            elapsed = time.perf_counter() - started
            if errors:
                logger.info(
                    "%s answered in %.2fs after %d failed provider(s)",
                    provider.name,
                    elapsed,
                    len(errors),
                )
            else:
                logger.info("%s answered in %.2fs", provider.name, elapsed)
            return analysis

        reason = "; ".join(errors) if errors else "no AI provider configured"
        logger.error("AI analysis unavailable, falling back. Reason: %s", reason)
        return fallback_analysis(reason)


def build_ai_service(settings: Settings) -> AIService:
    """Assemble the chain from AI_PROVIDER_CHAIN, preserving configured order."""
    from app.services.ai.anthropic_provider import AnthropicAnalyzer
    from app.services.ai.gemini import GeminiAnalyzer
    from app.services.ai.openai_provider import OpenAIAnalyzer

    registry: dict[str, type] = {
        "gemini": GeminiAnalyzer,
        "openai": OpenAIAnalyzer,
        "anthropic": AnthropicAnalyzer,
    }

    providers: list[AIAnalyzer] = []
    for name in settings.ai_providers:
        analyzer_cls = registry.get(name)
        if analyzer_cls is None:
            logger.warning("Unknown AI provider %r in AI_PROVIDER_CHAIN, ignoring", name)
            continue
        providers.append(analyzer_cls(settings))

    if not providers:
        logger.warning("AI_PROVIDER_CHAIN produced no providers; every request will fall back")

    return AIService(providers=providers, timeout=settings.ai_timeout_seconds)

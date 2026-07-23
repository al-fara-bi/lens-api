"""Anthropic (Claude) implementation of AIAnalyzer.

Named ``anthropic_provider`` rather than ``anthropic`` so the module never
shadows the installed package.

Uses structured outputs (``output_config.format``) so the model is constrained
to the shared JSON schema rather than asked politely and parsed hopefully.

Extended thinking is deliberately left off. Classifying a short contact message
is not a reasoning-heavy task, and this call sits in the request path with an
8-second budget — thinking would spend that budget without improving a
three-field answer. ``effort: low`` is set for the same reason.
"""

import logging

from anthropic import AsyncAnthropic

from app.core.config import Settings
from app.schemas.contact import AIAnalysis, ContactRequest
from app.services.ai.base import (
    ANALYSIS_JSON_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_analysis,
)

logger = logging.getLogger(__name__)


class AnthropicAnalyzer:
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.anthropic_api_key
        self._model = settings.anthropic_model
        self._timeout = settings.ai_timeout_seconds
        self._client: AsyncAnthropic | None = None

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            # max_retries=0: the provider chain is the retry strategy. Letting the
            # SDK retry internally would overrun the per-provider timeout and
            # delay the fallback.
            self._client = AsyncAnthropic(
                api_key=self._api_key, timeout=self._timeout, max_retries=0
            )
        return self._client

    async def analyze(self, payload: ContactRequest) -> AIAnalysis:
        response = await self._get_client().messages.create(
            model=self._model,
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(payload)}],
            output_config={
                "format": {"type": "json_schema", "schema": ANALYSIS_JSON_SCHEMA},
                "effort": "low",
            },
        )

        # Safety classifiers can decline a request with HTTP 200 and no content,
        # so stop_reason is checked before the content blocks are read.
        if response.stop_reason == "refusal":
            raise ValueError("Anthropic declined the request")

        raw = next(
            (block.text for block in response.content if block.type == "text"), ""
        ).strip()
        if not raw:
            raise ValueError("Anthropic returned an empty response")

        return parse_analysis(raw, self.name)

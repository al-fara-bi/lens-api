"""OpenAI implementation of AIAnalyzer.

Named ``openai_provider`` rather than ``openai`` so the module never competes
with the installed package name when reading imports.

Uses Structured Outputs in strict mode: the API guarantees the response validates
against the schema, which removes the "model returned almost-JSON" failure class.
Strict mode requires ``additionalProperties: false`` and every property listed in
``required`` — the shared schema already satisfies both.
"""

import logging

from openai import AsyncOpenAI

from app.core.config import Settings
from app.schemas.contact import AIAnalysis, ContactRequest
from app.services.ai.base import (
    ANALYSIS_JSON_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_analysis,
)

logger = logging.getLogger(__name__)


class OpenAIAnalyzer:
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.openai_api_key
        self._model = settings.openai_model
        self._timeout = settings.ai_timeout_seconds
        self._client: AsyncOpenAI | None = None

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            # max_retries=0: the chain is the retry strategy. Letting the SDK
            # retry internally would blow past the per-provider timeout budget
            # and delay the fallback.
            self._client = AsyncOpenAI(
                api_key=self._api_key, timeout=self._timeout, max_retries=0
            )
        return self._client

    async def analyze(self, payload: ContactRequest) -> AIAnalysis:
        response = await self._get_client().chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(payload)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "contact_analysis",
                    "strict": True,
                    "schema": ANALYSIS_JSON_SCHEMA,
                },
            },
            temperature=0.3,
            max_completion_tokens=800,
        )

        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError("OpenAI returned an empty response")

        return parse_analysis(raw, self.name)

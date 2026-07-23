"""Shared implementation for any OpenAI-compatible chat completions API.

Several providers speak OpenAI's wire protocol verbatim — the only differences
are the endpoint, the model name, and the key. Rather than copy the request
shape per provider, the call lives here once and each provider supplies its own
three values.

Structured Outputs in strict mode are used where available: the API guarantees
the response validates against the schema, which removes the "model returned
almost-JSON" failure class entirely.
"""

import logging

from openai import AsyncOpenAI

from app.schemas.contact import AIAnalysis, ContactRequest
from app.services.ai.base import (
    ANALYSIS_JSON_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_analysis,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleAnalyzer:
    """Base class. Subclasses set ``name`` and pass endpoint/model/key."""

    name: str = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._base_url = base_url
        self._client: AsyncOpenAI | None = None

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            # max_retries=0: the provider chain is the retry strategy. Letting the
            # SDK retry internally would overrun the per-provider timeout budget
            # and delay the fallback.
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,  # None keeps the SDK's own default
                timeout=self._timeout,
                max_retries=0,
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
                    # Requires additionalProperties: false and every property
                    # listed in required — the shared schema satisfies both.
                    "strict": True,
                    "schema": ANALYSIS_JSON_SCHEMA,
                },
            },
            temperature=0.3,
            max_completion_tokens=800,
        )

        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError(f"{self.name} returned an empty response")

        return parse_analysis(raw, self.name)

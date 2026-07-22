"""Google Gemini implementation of AIAnalyzer.

Uses the google-genai SDK's async surface (``client.aio``) and constrained JSON
output, so the model cannot answer with prose that then fails to parse.
"""

import logging

from google import genai
from google.genai import types

from app.core.config import Settings
from app.schemas.contact import AIAnalysis, ContactRequest
from app.services.ai.base import (
    ANALYSIS_JSON_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_analysis,
)

logger = logging.getLogger(__name__)

# Gemini's JSON-schema validator rejects some vocabulary that OpenAI requires,
# so the shared schema is narrowed here rather than duplicated wholesale.
_GEMINI_SCHEMA = {k: v for k, v in ANALYSIS_JSON_SCHEMA.items() if k != "additionalProperties"}


class GeminiAnalyzer:
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_model
        self._client: genai.Client | None = None

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> genai.Client:
        # Built lazily so an unconfigured provider never constructs a client.
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def analyze(self, payload: ContactRequest) -> AIAnalysis:
        response = await self._get_client().aio.models.generate_content(
            model=self._model,
            contents=build_user_prompt(payload),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_json_schema=_GEMINI_SCHEMA,
                temperature=0.3,
                max_output_tokens=800,
            ),
        )

        raw = (response.text or "").strip()
        if not raw:
            raise ValueError("Gemini returned an empty response")

        return parse_analysis(raw, self.name)

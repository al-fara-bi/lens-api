"""Groq implementation of AIAnalyzer.

Groq exposes an OpenAI-compatible endpoint, so the whole request is inherited
from OpenAICompatibleAnalyzer and only the base URL and model differ.

Chosen because it issues API keys without a payment method and has no regional
restriction on its free tier — the two problems that made Gemini unusable here.
"""

from app.core.config import Settings
from app.services.ai.openai_compatible import OpenAICompatibleAnalyzer

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqAnalyzer(OpenAICompatibleAnalyzer):
    name = "groq"

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            timeout=settings.ai_timeout_seconds,
            base_url=GROQ_BASE_URL,
        )

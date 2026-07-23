"""OpenAI implementation of AIAnalyzer.

Named ``openai_provider`` rather than ``openai`` so the module never competes
with the installed package name when reading imports.

The request itself lives in OpenAICompatibleAnalyzer — this class only supplies
the credentials and model.
"""

from app.core.config import Settings
from app.services.ai.openai_compatible import OpenAICompatibleAnalyzer


class OpenAIAnalyzer(OpenAICompatibleAnalyzer):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout=settings.ai_timeout_seconds,
            # No base_url: the SDK already points at api.openai.com.
        )

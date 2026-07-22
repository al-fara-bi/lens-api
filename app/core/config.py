"""Application settings, loaded from environment variables / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- app ----------
    app_name: str = "Lens API"
    # Injected at deploy time from the git tag, so /api/health tells you exactly
    # which revision is running instead of a constant baked into the source.
    app_version: str = "dev"
    environment: str = "development"
    debug: bool = True

    # Comma-separated rather than a list: pydantic-settings parses list fields as
    # JSON, so `CORS_ORIGINS=http://a,http://b` would raise a decode error.
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # ---------- storage ----------
    data_dir: Path = Path("./data")
    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    # ---------- rate limiting ----------
    rate_limit_max_requests: int = 5
    rate_limit_window_seconds: int = 3600

    # ---------- AI ----------
    ai_provider_chain: str = "gemini,openai"
    ai_timeout_seconds: float = 8.0

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ---------- mail ----------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    mail_from: str = ""
    mail_from_name: str = "Lens"
    owner_email: str = ""

    # ---------- derived ----------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_providers(self) -> list[str]:
        return [p.strip().lower() for p in self.ai_provider_chain.split(",") if p.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def request_log_path(self) -> Path:
        return self.data_dir / "requests.log"

    @property
    def app_log_path(self) -> Path:
        return self.data_dir / "app.log"

    @property
    def rate_limit_state_path(self) -> Path:
        return self.data_dir / "rate_limit.json"

    @property
    def mail_configured(self) -> bool:
        return bool(self.smtp_host and self.mail_from and self.owner_email)


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is read once per process."""
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings

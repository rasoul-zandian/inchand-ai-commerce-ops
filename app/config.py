"""Application settings loaded from environment variables and optional `.env` file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Runtime configuration; secrets must not be committed (use `.env` locally, never in git)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Inchand AI Commerce Operations Copilot"
    environment: str = "development"
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "inchand-ai-commerce-mvp"
    llm_provider: str = "mock"
    llm_model: str = "mock-vendor-ticket-drafter"
    openai_api_key: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached settings. Call `get_settings.cache_clear()` in tests when overriding environment."""
    return AppSettings()

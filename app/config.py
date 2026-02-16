"""
Centralized application configuration.

All settings are driven by environment variables with sensible defaults.
Uses Pydantic BaseSettings for validation and type coercion.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Application ---
    app_name: str = "Negocia"
    app_version: str = "0.1.0"
    environment: str = "development"  # development | staging | production
    debug: bool = True
    log_level: str = "INFO"  # DEBUG | INFO | WARNING | ERROR

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Redis (Phase 2+) ---
    redis_url: str = "redis://localhost:6379/0"

    # --- CORS ---
    allowed_origins: list[str] = ["*"]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    Using lru_cache ensures we only read env vars once, and the same
    Settings object is reused across the application lifetime.
    """
    return Settings()

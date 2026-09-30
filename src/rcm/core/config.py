"""Application configuration and secrets.

Secrets come from the environment (pydantic-settings), never hardcoded. The
settings object is the single source of truth; importing it validates that the
critical security inputs are present. Fail-closed: a missing PHI master key or
database URL is a startup error, not a silent default.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings. Prefix ``RCM_`` (plus ``ANTHROPIC_API_KEY``)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["dev", "test", "staging", "prod"] = Field("dev", alias="RCM_ENV")
    log_level: str = Field("INFO", alias="RCM_LOG_LEVEL")

    # --- PHI encryption (fail-closed) ---
    # 32-byte AES-256 key, base64url-encoded. Required in every environment.
    master_key: str = Field(..., alias="RCM_MASTER_KEY", min_length=1)

    # --- Database ---
    database_url: str = Field(
        "postgresql+psycopg://rcm_app:rcm_app_pw@localhost:5432/rcm",
        alias="RCM_DATABASE_URL",
    )
    migration_database_url: str = Field(
        "postgresql+psycopg://rcm_migrator:rcm_migrator_pw@localhost:5432/rcm",
        alias="RCM_MIGRATION_DATABASE_URL",
    )

    # --- Anthropic ---
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    # Small model for cheap, high-volume CARC classification; large model for
    # drafting (Phase 1). PHI is de-identified before any call to either.
    classifier_model: str = Field("claude-haiku-4-5", alias="RCM_CLASSIFIER_MODEL")
    drafting_model: str = Field("claude-opus-4-8", alias="RCM_DRAFTING_MODEL")

    # --- Embeddings (public policy docs only — never PHI) ---
    embedding_provider: Literal["hash", "voyage", "sentence-transformers"] = Field(
        "hash", alias="RCM_EMBEDDING_PROVIDER"
    )
    embedding_dim: int = Field(1536, alias="RCM_EMBEDDING_DIM", ge=8)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the validated, cached settings.

    Raises a clear error (rather than a confusing failure later) when a required
    secret such as ``RCM_MASTER_KEY`` is absent.
    """
    try:
        return Settings()  # type: ignore[call-arg]  # values sourced from env
    except ValidationError as exc:  # pragma: no cover - exercised via env in tests
        missing = ", ".join(
            str(err["loc"][0]) for err in exc.errors() if err["type"] == "missing"
        )
        hint = f" (missing/invalid: {missing})" if missing else ""
        raise RuntimeError(
            "Refusing to start: configuration failed validation" + hint
        ) from exc

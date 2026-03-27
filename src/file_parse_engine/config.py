"""Configuration management via Pydantic Settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

# Strategy type alias for clarity
ParseStrategy = Literal["fast", "ocr", "hybrid", "vlm"]


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FPE_",
        extra="ignore",
    )

    # --- Parse Strategy ---
    strategy: ParseStrategy = "fast"

    # --- VLM Routes ---
    vlm_routes_file: str = ""  # Custom YAML path; empty = auto-detect

    # --- VLM Provider Keys ---
    # Accept both FPE_OPENROUTER_API_KEY and OPENROUTER_API_KEY
    openrouter_api_key: str = ""
    siliconflow_api_key: str = ""

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        """Add fallback to non-prefixed env vars for API keys."""
        import os

        sources = super().settings_customise_sources(settings_cls, **kwargs)
        return sources

    def __init__(self, **kwargs):
        import os

        # Fallback: read non-prefixed env vars if prefixed ones are not set
        if not kwargs.get("openrouter_api_key") and not os.environ.get("FPE_OPENROUTER_API_KEY"):
            kwargs.setdefault("openrouter_api_key", os.environ.get("OPENROUTER_API_KEY", ""))
        if not kwargs.get("siliconflow_api_key") and not os.environ.get("FPE_SILICONFLOW_API_KEY"):
            kwargs.setdefault("siliconflow_api_key", os.environ.get("SILICONFLOW_API_KEY", ""))

        super().__init__(**kwargs)

    # --- Enrichment ---
    enrich_links: bool = False   # Inject real PDF links into output (any strategy)
    extract_images: bool = False  # Export embedded images & inject into Markdown

    # --- VLM Behavior ---
    vlm_model_override: str = ""  # CLI --model override; empty = use routes default
    vlm_concurrency: int = 10
    vlm_timeout: int = 60

    # --- Image Processing ---
    image_dpi: int = 200
    image_max_size: int = 4096
    image_quality: int = 85

    # --- Output ---
    output_dir: str = "output"

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings (useful for testing)."""
    global _settings
    _settings = None

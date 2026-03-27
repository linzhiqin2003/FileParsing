"""VLM model routing — load provider / model / task mapping from YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from file_parse_engine.utils.logger import get_logger

logger = get_logger("vlm.routes")

_PACKAGE_DIR = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """A VLM API provider (e.g. OpenRouter, SiliconFlow)."""

    name: str
    base_url: str
    api_key_env: str

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        # Fallback: try without FPE_ prefix
        if not key and self.api_key_env.startswith("FPE_"):
            key = os.environ.get(self.api_key_env[4:], "")
        return key

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass
class ModelConfig:
    """A specific model served by a provider."""

    name: str
    provider: str  # references ProviderConfig.name
    model_id: str
    max_tokens: int = 8192
    temperature: float = 0.1
    input_price: float = 0.0   # $/M tokens
    output_price: float = 0.0  # $/M tokens


@dataclass
class RouteConfig:
    """Complete routing configuration parsed from YAML."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    models: dict[str, ModelConfig] = field(default_factory=dict)
    routes: dict[str, str] = field(default_factory=dict)  # task → model name
    primary: str = ""
    fallback: str = ""
    concurrency: int = 5
    timeout: int = 60

    # -- helpers ---------------------------------------------------

    def get_model_for_task(self, task: str) -> ModelConfig | None:
        """Resolve *task* (e.g. ``"document"``) → ModelConfig."""
        model_name = self.routes.get(task, self.primary)
        return self.models.get(model_name)

    def get_provider_for_model(self, model: ModelConfig) -> ProviderConfig | None:
        return self.providers.get(model.provider)

    def get_primary_model(self) -> ModelConfig | None:
        return self.models.get(self.primary)

    def get_fallback_model(self) -> ModelConfig | None:
        return self.models.get(self.fallback) if self.fallback else None


# ------------------------------------------------------------------
# Loader
# ------------------------------------------------------------------

def load_routes(custom_path: str = "") -> RouteConfig:
    """Load the VLM route configuration from YAML.

    Search order:
    1. *custom_path* (explicit)
    2. ``./vlm_routes.yaml`` in the current working directory
    3. Package-bundled default
    """
    yaml_path = _find_routes_yaml(custom_path)
    logger.debug("Loading VLM routes from: %s", yaml_path)

    with open(yaml_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    return _parse_config(data)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _find_routes_yaml(custom_path: str) -> Path:
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"VLM routes file not found: {custom_path}")

    # Current working directory override
    cwd_path = Path.cwd() / "vlm_routes.yaml"
    if cwd_path.exists():
        return cwd_path

    # Package default
    default_path = _PACKAGE_DIR / "vlm_routes.yaml"
    if default_path.exists():
        return default_path

    raise FileNotFoundError(
        "No vlm_routes.yaml found.  "
        "Place one in the working directory or set FPE_VLM_ROUTES_FILE."
    )


def _parse_config(data: dict) -> RouteConfig:
    config = RouteConfig()

    for name, prov in data.get("providers", {}).items():
        config.providers[name] = ProviderConfig(
            name=name,
            base_url=prov["base_url"],
            api_key_env=prov["api_key_env"],
        )

    for name, mod in data.get("models", {}).items():
        pricing = mod.get("pricing", {})
        config.models[name] = ModelConfig(
            name=name,
            provider=mod["provider"],
            model_id=mod["model_id"],
            max_tokens=mod.get("max_tokens", 8192),
            temperature=mod.get("temperature", 0.1),
            input_price=float(pricing.get("input", 0.0)),
            output_price=float(pricing.get("output", 0.0)),
        )

    config.routes = dict(data.get("routes", {}))

    defaults = data.get("defaults", {})
    config.primary = defaults.get("primary", "")
    config.fallback = defaults.get("fallback", "")
    config.concurrency = defaults.get("concurrency", 5)
    config.timeout = defaults.get("timeout", 60)

    return config

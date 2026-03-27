"""Tests for VLM route configuration loading."""

from pathlib import Path

import pytest

from file_parse_engine.vlm.routes import RouteConfig, load_routes, _parse_config


class TestRouteConfigParsing:
    """Test YAML → RouteConfig parsing."""

    def test_parse_minimal(self):
        data = {
            "providers": {
                "test_provider": {
                    "base_url": "https://example.com/v1",
                    "api_key_env": "TEST_KEY",
                },
            },
            "models": {
                "test_model": {
                    "provider": "test_provider",
                    "model_id": "test/model-v1",
                },
            },
            "routes": {"document": "test_model"},
            "defaults": {
                "primary": "test_model",
                "concurrency": 3,
                "timeout": 30,
            },
        }
        rc = _parse_config(data)

        assert "test_provider" in rc.providers
        assert rc.providers["test_provider"].base_url == "https://example.com/v1"

        assert "test_model" in rc.models
        assert rc.models["test_model"].model_id == "test/model-v1"

        assert rc.routes["document"] == "test_model"
        assert rc.primary == "test_model"
        assert rc.concurrency == 3
        assert rc.timeout == 30

    def test_get_model_for_task(self):
        rc = RouteConfig(
            models={"m1": None},  # type: ignore[arg-type]
            routes={"document": "m1"},
            primary="m1",
        )
        # Task in routes → returns that model name lookup
        assert rc.routes.get("document") == "m1"
        # Task NOT in routes → falls back to primary
        assert rc.routes.get("unknown", rc.primary) == "m1"


class TestDefaultRoutesLoading:
    """Test that the package-bundled vlm_routes.yaml loads correctly."""

    def test_load_package_default(self):
        rc = load_routes()
        assert len(rc.providers) > 0
        assert len(rc.models) > 0
        assert rc.primary != ""

    def test_providers_have_required_fields(self):
        rc = load_routes()
        for p in rc.providers.values():
            assert p.base_url.startswith("http")
            assert p.api_key_env.startswith("FPE_")

    def test_models_reference_valid_providers(self):
        rc = load_routes()
        for m in rc.models.values():
            assert m.provider in rc.providers

    def test_routes_reference_valid_models(self):
        rc = load_routes()
        for task, model_name in rc.routes.items():
            assert model_name in rc.models, f"Route '{task}' → '{model_name}' not in models"

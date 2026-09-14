import pytest

from lorcana.coach.runtime import build_analyzer_registry
from lorcana.config import ConfigurationError, Settings


def test_analyzer_registry_is_empty_when_coach_is_disabled():
    registry = build_analyzer_registry(Settings())
    with pytest.raises(Exception, match="not configured"):
        registry.create("openai")


def test_openai_registry_requires_secret():
    settings = Settings(coach_analyzer_name="openai")
    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        build_analyzer_registry(settings)


def test_openai_registry_builds_configured_model():
    settings = Settings(
        coach_analyzer_name="openai",
        openai_api_key="secret",
        openai_coach_model="gpt-custom",
    )
    registry = build_analyzer_registry(settings)
    analyzer = registry.create("openai")
    try:
        assert analyzer.provider == "openai"
        assert analyzer.model == "gpt-custom"
    finally:
        analyzer.close()


def test_unknown_analyzer_is_rejected():
    with pytest.raises(ConfigurationError, match="Unsupported"):
        build_analyzer_registry(Settings(coach_analyzer_name="mystery"))

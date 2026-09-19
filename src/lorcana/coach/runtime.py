"""Process-level Coach analyzer composition."""

from __future__ import annotations

from lorcana.coach.openai_analyzer import OpenAIResponsesCoachAnalyzer
from lorcana.coach.registry import AnalyzerRegistry
from lorcana.coach.rules import load_bundle
from lorcana.config import ConfigurationError, Settings


def build_analyzer_registry(settings: Settings) -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    name = settings.coach_analyzer_name
    if name is None:
        return registry
    if name != "openai":
        raise ConfigurationError(f"Unsupported LORCANA_COACH_ANALYZER: {name}")
    if settings.openai_api_key is None:
        raise ConfigurationError("OPENAI_API_KEY is required when LORCANA_COACH_ANALYZER=openai")
    api_key = settings.openai_api_key
    model = settings.openai_coach_model
    registry.register(
        "openai",
        lambda: OpenAIResponsesCoachAnalyzer(api_key=api_key, model=model,
            rules_bundle=load_bundle(settings.coach_rules_bundle)),
    )
    return registry

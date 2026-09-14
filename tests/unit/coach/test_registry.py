from __future__ import annotations

import pytest

from lorcana.coach.registry import AnalyzerNotConfiguredError, AnalyzerRegistry


class Analyzer:
    provider = "fake"
    model = "m"
    prompt_version = "p"

    def analyze(self, evidence):  # pragma: no cover - registry does not invoke it
        raise NotImplementedError


def test_registry_normalizes_names_and_creates_fresh_analyzers():
    registry = AnalyzerRegistry()
    registry.register(" Primary ", Analyzer)
    assert registry.names() == ("primary",)
    assert isinstance(registry.create("PRIMARY"), Analyzer)
    assert registry.create("primary") is not registry.create("primary")


def test_registry_rejects_duplicates_and_missing_names():
    registry = AnalyzerRegistry()
    registry.register("primary", Analyzer)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("PRIMARY", Analyzer)
    with pytest.raises(AnalyzerNotConfiguredError, match="not configured"):
        registry.create("missing")

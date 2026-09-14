"""Provider-agnostic analyzer boundary.

A live model adapter can be added without changing Coach persistence or replay
access rules. Unit/integration tests use deterministic fake analyzers.
"""

from __future__ import annotations

from typing import Any, Protocol

from lorcana.coach.types import CoachAnalyzerResult


class CoachAnalyzer(Protocol):
    provider: str
    model: str
    prompt_version: str

    def analyze(self, evidence: dict[str, Any]) -> CoachAnalyzerResult: ...

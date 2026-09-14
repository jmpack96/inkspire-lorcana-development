"""Runtime registry for Coach analyzer adapters.

Jobs persist only a stable analyzer name. Credentials and live provider clients are
resolved by the worker process, never serialized into job payloads.
"""

from __future__ import annotations

from collections.abc import Callable

from lorcana.coach.analyzer import CoachAnalyzer

AnalyzerFactory = Callable[[], CoachAnalyzer]


class AnalyzerNotConfiguredError(LookupError):
    pass


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, AnalyzerFactory] = {}

    def register(self, name: str, factory: AnalyzerFactory) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("analyzer name must not be empty")
        if key in self._factories:
            raise ValueError(f"analyzer already registered: {key}")
        self._factories[key] = factory

    def create(self, name: str) -> CoachAnalyzer:
        key = name.strip().lower()
        factory = self._factories.get(key)
        if factory is None:
            raise AnalyzerNotConfiguredError(f"Coach analyzer is not configured: {key or '<empty>'}")
        return factory()

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

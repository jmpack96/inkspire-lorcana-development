"""Composition root for process-level resources."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from lorcana.config import Settings
from lorcana.db.engine import create_database_engine


@dataclass
class ApplicationResources:
    settings: Settings
    engine: Engine

    @classmethod
    def from_env(cls) -> "ApplicationResources":
        settings = Settings.from_env()
        return cls(settings=settings, engine=create_database_engine(settings.sqlalchemy_database_url()))

    def close(self) -> None:
        self.engine.dispose()

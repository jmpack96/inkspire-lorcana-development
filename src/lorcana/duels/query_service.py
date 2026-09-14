"""Read service for selecting Coach-ready Duels evidence."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from typing import ContextManager
from uuid import UUID

from sqlalchemy.engine import Connection, Engine

from lorcana.duels.features import FEATURE_EXTRACTOR_VERSION
from lorcana.duels.query_repository import DuelsQueryRepository
from lorcana.duels.query_types import ReplayEvidenceRef
from lorcana.duels.replay_parser import PARSER_VERSION

ReadConnectionFactory = Callable[[], ContextManager[Connection]]


class DuelsQueryService:
    def __init__(self, *, repository: DuelsQueryRepository, read_connection_factory: ReadConnectionFactory) -> None:
        self.repository = repository
        self.read_connection_factory = read_connection_factory

    @classmethod
    def from_engine(cls, engine: Engine) -> "DuelsQueryService":
        @contextmanager
        def reader():
            with engine.connect() as connection:
                yield connection
        return cls(repository=DuelsQueryRepository(), read_connection_factory=reader)

    def latest_evidence_for_game(self, member_id: UUID, game_id: str) -> ReplayEvidenceRef | None:
        game = game_id.strip()
        if not game:
            return None
        with self.read_connection_factory() as connection:
            row = self.repository.latest_evidence_for_game(
                connection,
                member_id=member_id,
                game_id=game,
                parser_version=PARSER_VERSION,
                extractor_version=FEATURE_EXTRACTOR_VERSION,
            )
        return None if row is None else ReplayEvidenceRef(**dict(row))

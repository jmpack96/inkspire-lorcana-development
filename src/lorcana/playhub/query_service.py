"""Application read models for Play Hub data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import ContextManager
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.engine import Connection, Engine

from lorcana.playhub.query_repository import PlayHubQueryRepository

ConnectionFactory = Callable[[], ContextManager[Connection]]


@dataclass(frozen=True)
class LatestImport:
    import_attempt_id: UUID
    event_id: int
    started_at: datetime
    completed_at: datetime | None
    status: str


@dataclass(frozen=True)
class DatabaseStatus:
    events: int
    stores: int
    players: int
    matches: int
    two_player_matches: int
    multiplayer_matches: int
    unknown_participants: int
    latest_import: LatestImport | None


@dataclass(frozen=True)
class SetChampionshipEvent:
    event_id: int
    event_name: str
    start_datetime: datetime | None
    end_datetime: datetime | None
    player_count: int | None
    capacity: int | None
    source_url: str | None
    store_id: str
    store_name: str
    city: str | None
    state_region: str | None
    country: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class TeamEvent:
    event_id: int
    name: str
    start_datetime: datetime
    format: str | None
    source_url: str | None
    player_ids: tuple[int, ...]


class PlayHubQueryService:
    def __init__(self, *, repository: PlayHubQueryRepository, connection_factory: ConnectionFactory):
        self.repository = repository
        self.connection_factory = connection_factory

    @classmethod
    def from_engine(cls, engine: Engine, *, repository: PlayHubQueryRepository | None = None):
        return cls(repository=repository or PlayHubQueryRepository(), connection_factory=engine.connect)

    def database_status(self) -> DatabaseStatus:
        with self.connection_factory() as connection:
            counts = self.repository.database_counts(connection)
            latest = self.repository.latest_import(connection)
        return DatabaseStatus(
            **counts,
            latest_import=None if latest is None else LatestImport(**dict(latest)),
        )

    def houston_set_championships(self, set_name: str) -> tuple[SetChampionshipEvent, ...]:
        if not set_name.strip():
            raise ValueError("set_name must not be empty")
        with self.connection_factory() as connection:
            rows = self.repository.find_set_championships(
                connection,
                set_name=set_name,
                city="Houston",
                state_values=("TX", "TEXAS"),
                country_values=("US", "USA", "UNITED STATES"),
            )
        return tuple(SetChampionshipEvent(**dict(row)) for row in rows)

    def recent_events_for_players(
        self,
        player_ids,
        *,
        days: int = 7,
        now: datetime | None = None,
    ) -> tuple[TeamEvent, ...]:
        if days <= 0:
            raise ValueError("days must be positive")
        end_at = now or datetime.now(timezone.utc)
        if end_at.tzinfo is None or end_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        # Match the old calendar-day behavior while using real timestamptz bounds.
        end_at = end_at.astimezone(timezone.utc)
        start_day = end_at.date() - timedelta(days=days - 1)
        start_at = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
        ids = tuple(dict.fromkeys(int(value) for value in player_ids))
        with self.connection_factory() as connection:
            rows = self.repository.recent_event_player_rows(
                connection, player_ids=ids, start_at=start_at, end_at=end_at
            )
        events: list[TeamEvent] = []
        by_id: dict[int, dict] = {}
        for row in rows:
            event_id = row["event_id"]
            if event_id not in by_id:
                data = {
                    "event_id": event_id,
                    "name": row["name"],
                    "start_datetime": row["start_datetime"],
                    "format": row["format"],
                    "source_url": row["source_url"],
                    "player_ids": [],
                }
                by_id[event_id] = data
            if row["player_id"] not in by_id[event_id]["player_ids"]:
                by_id[event_id]["player_ids"].append(row["player_id"])
        for data in by_id.values():
            data["player_ids"] = tuple(data["player_ids"])
            events.append(TeamEvent(**data))
        return tuple(events)

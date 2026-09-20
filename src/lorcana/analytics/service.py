"""Application service for Discord command usage analytics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import ContextManager

from sqlalchemy.engine import Connection, Engine

from lorcana.analytics.repository import DiscordUsageRepository
from lorcana.db.tx import transaction

ConnectionFactory = Callable[[], ContextManager[Connection]]
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CommandUsageEntry:
    command_name: str
    invocations: int
    unique_users: int
    failures: int
    average_duration_ms: int
    team_selector_invocations: int


@dataclass(frozen=True)
class CommandUsageSummary:
    days: int
    invocations: int
    unique_users: int
    failures: int
    entries: tuple[CommandUsageEntry, ...]


class DiscordUsageService:
    def __init__(
        self,
        *,
        repository: DiscordUsageRepository,
        transaction_factory: ConnectionFactory,
        connection_factory: ConnectionFactory,
        clock: Clock = utc_now,
    ) -> None:
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.clock = clock

    @classmethod
    def from_engine(cls, engine: Engine) -> "DiscordUsageService":
        return cls(
            repository=DiscordUsageRepository(),
            transaction_factory=lambda: transaction(engine),
            connection_factory=engine.connect,
        )

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("DiscordUsageService clock must return a timezone-aware datetime")
        return now.astimezone(timezone.utc)

    def record(
        self,
        *,
        command_name: str,
        invocation_mode: str,
        discord_user_id: int,
        guild_id: int | None,
        succeeded: bool,
        duration_ms: int,
    ) -> None:
        if not command_name.strip():
            raise ValueError("command_name must not be empty")
        if not invocation_mode.strip():
            raise ValueError("invocation_mode must not be empty")
        if duration_ms < 0:
            raise ValueError("duration_ms must not be negative")
        with self.transaction_factory() as connection:
            self.repository.record(
                connection,
                occurred_at=self._now(),
                command_name=command_name.strip(),
                invocation_mode=invocation_mode.strip(),
                discord_user_id=int(discord_user_id),
                guild_id=None if guild_id is None else int(guild_id),
                succeeded=bool(succeeded),
                duration_ms=int(duration_ms),
            )

    def summary(self, *, days: int = 30) -> CommandUsageSummary:
        if days < 1 or days > 365:
            raise ValueError("days must be between 1 and 365")
        start_at = self._now() - timedelta(days=days)
        with self.connection_factory() as connection:
            overall = self.repository.overall(connection, start_at=start_at)
            rows = self.repository.summary_rows(connection, start_at=start_at)
        entries = tuple(
            CommandUsageEntry(
                command_name=row["command_name"],
                invocations=int(row["invocations"]),
                unique_users=int(row["unique_users"]),
                failures=int(row["failures"] or 0),
                average_duration_ms=int(round(float(row["average_duration_ms"] or 0))),
                team_selector_invocations=int(row["team_selector_invocations"] or 0),
            )
            for row in rows
        )
        return CommandUsageSummary(
            days=days,
            invocations=int(overall["invocations"] or 0),
            unique_users=int(overall["unique_users"] or 0),
            failures=int(overall["failures"] or 0),
            entries=entries,
        )

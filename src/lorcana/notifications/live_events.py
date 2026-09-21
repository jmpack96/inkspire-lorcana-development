"""Strict live-event detection and durable Discord delivery state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import ContextManager
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from lorcana.db.schema.identity import member_playhub_links, members, team_memberships, teams
from lorcana.db.schema.notifications import discord_live_event_announcements
from lorcana.db.schema.playhub import playhub_events, playhub_registrations
from lorcana.db.tx import transaction

ConnectionFactory = Callable[[], ContextManager[Connection]]


@dataclass(frozen=True)
class PendingAnnouncement:
    announcement_id: int
    event_id: int
    channel_id: int
    event_url: str
    message_content: str
    expires_at: datetime
    attempt_count: int


def format_live_event_message(
    event_name: str,
    player_names: tuple[str, ...],
    event_url: str,
) -> str:
    names = ", ".join(sorted(set(player_names), key=str.casefold))
    content = f"**{event_name.strip()}**\nPlaying: {names}\n{event_url.strip()}"
    if len(content) <= 2000:
        return content
    fixed_length = len(event_url.strip()) + len("\nPlaying: \n")
    name_limit = min(300, max(1, 2000 - fixed_length - 4))
    event_label = event_name.strip()[:name_limit]
    prefix = f"**{event_label}**\nPlaying: "
    available_names = max(1, 2000 - len(prefix) - len(event_url.strip()) - 2)
    return f"{prefix}{names[:available_names]}\n{event_url.strip()}"


def event_date_is_current(
    start_datetime: datetime,
    timezone_name: str | None,
    now: datetime,
) -> bool:
    """Reject stale source records using the event's own calendar date."""
    if not timezone_name:
        return False
    try:
        event_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return False
    return start_datetime.astimezone(event_timezone).date() == now.astimezone(
        event_timezone
    ).date()


def _live_status_clause():
    return or_(
        func.upper(func.trim(playhub_events.c.display_status)) == "LIVE",
        func.upper(func.trim(playhub_events.c.event_status)) == "LIVE",
        func.upper(func.trim(playhub_events.c.lifecycle_status)) == "LIVE",
    )


class LiveEventAlertRepository:
    @staticmethod
    def _team_events(team_slug: str):
        return (
            playhub_events.join(
                playhub_registrations,
                playhub_registrations.c.event_id == playhub_events.c.event_id,
            )
            .join(
                member_playhub_links,
                member_playhub_links.c.player_id == playhub_registrations.c.player_id,
            )
            .join(members, members.c.member_id == member_playhub_links.c.member_id)
            .join(team_memberships, team_memberships.c.member_id == members.c.member_id)
            .join(teams, teams.c.team_id == team_memberships.c.team_id)
        )

    def potential_event_ids(
        self,
        connection: Connection,
        *,
        team_slug: str,
        now: datetime,
        limit: int,
    ) -> tuple[int, ...]:
        rows = connection.execute(
            select(playhub_events.c.event_id)
            .select_from(self._team_events(team_slug))
            .where(
                teams.c.slug == team_slug,
                teams.c.status == "active",
                members.c.status == "active",
                team_memberships.c.ended_at.is_(None),
                playhub_events.c.start_datetime.is_not(None),
                playhub_events.c.end_datetime.is_not(None),
                playhub_events.c.start_datetime <= now,
                playhub_events.c.end_datetime > now,
            )
            .distinct()
            .order_by(playhub_events.c.event_id)
            .limit(limit)
        ).scalars().all()
        return tuple(int(value) for value in rows)

    def eligible_events(
        self,
        connection: Connection,
        *,
        team_slug: str,
        now: datetime,
        fresh_after: datetime,
    ):
        return connection.execute(
            select(
                playhub_events.c.event_id,
                playhub_events.c.name.label("event_name"),
                playhub_events.c.source_url,
                playhub_events.c.end_datetime,
                playhub_events.c.start_datetime,
                playhub_events.c.timezone,
                members.c.preferred_display_name.label("player_name"),
            )
            .select_from(self._team_events(team_slug))
            .where(
                teams.c.slug == team_slug,
                teams.c.status == "active",
                members.c.status == "active",
                team_memberships.c.ended_at.is_(None),
                func.upper(func.trim(playhub_registrations.c.registration_status)) == "ACTIVE",
                playhub_registrations.c.last_synced >= fresh_after,
                playhub_events.c.last_synced >= fresh_after,
                playhub_events.c.start_datetime <= now,
                playhub_events.c.end_datetime > now,
                playhub_events.c.source_url.is_not(None),
                func.length(func.trim(playhub_events.c.source_url)) > 0,
                _live_status_clause(),
            )
            .distinct()
            .order_by(playhub_events.c.event_id)
        ).mappings().all()

    def reserve(
        self,
        connection: Connection,
        *,
        event_id: int,
        channel_id: int,
        event_url: str,
        message_content: str,
        expires_at: datetime,
        now: datetime,
    ) -> bool:
        statement = (
            pg_insert(discord_live_event_announcements)
            .values(
                event_id=event_id,
                channel_id=channel_id,
                event_url=event_url,
                message_content=message_content,
                expires_at=expires_at,
                status="pending",
                attempt_count=0,
                created_at=now,
                next_attempt_at=now,
            )
            .on_conflict_do_nothing(
                constraint="uq_live_event_announcement_event_channel"
            )
            .returning(discord_live_event_announcements.c.announcement_id)
        )
        return connection.execute(statement).scalar_one_or_none() is not None

    def next_pending(self, connection: Connection, *, now: datetime):
        return connection.execute(
            select(
                discord_live_event_announcements.c.announcement_id,
                discord_live_event_announcements.c.event_id,
                discord_live_event_announcements.c.channel_id,
                discord_live_event_announcements.c.event_url,
                discord_live_event_announcements.c.message_content,
                discord_live_event_announcements.c.expires_at,
                discord_live_event_announcements.c.attempt_count,
            )
            .where(
                discord_live_event_announcements.c.status == "pending",
                discord_live_event_announcements.c.next_attempt_at <= now,
                discord_live_event_announcements.c.expires_at > now,
            )
            .order_by(discord_live_event_announcements.c.created_at)
            .limit(1)
        ).mappings().one_or_none()

    def mark_sent(
        self,
        connection: Connection,
        *,
        announcement_id: int,
        message_id: int,
        sent_at: datetime,
    ) -> None:
        connection.execute(
            update(discord_live_event_announcements)
            .where(discord_live_event_announcements.c.announcement_id == announcement_id)
            .values(status="sent", discord_message_id=message_id, sent_at=sent_at, last_error=None)
        )

    def mark_failed(
        self,
        connection: Connection,
        *,
        announcement_id: int,
        attempt_count: int,
        next_attempt_at: datetime,
        error: str,
    ) -> None:
        connection.execute(
            update(discord_live_event_announcements)
            .where(discord_live_event_announcements.c.announcement_id == announcement_id)
            .values(
                attempt_count=attempt_count,
                next_attempt_at=next_attempt_at,
                last_error=error[:500],
            )
        )


class LiveEventAlertService:
    def __init__(
        self,
        *,
        repository: LiveEventAlertRepository,
        connection_factory: ConnectionFactory,
        transaction_factory: ConnectionFactory,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repository = repository
        self.connection_factory = connection_factory
        self.transaction_factory = transaction_factory
        self.clock = clock

    @classmethod
    def from_engine(cls, engine: Engine) -> "LiveEventAlertService":
        return cls(
            repository=LiveEventAlertRepository(),
            connection_factory=engine.connect,
            transaction_factory=lambda: transaction(engine),
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LiveEventAlertService clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def potential_event_ids(self, team_slug: str, *, limit: int = 50) -> tuple[int, ...]:
        with self.connection_factory() as connection:
            return self.repository.potential_event_ids(
                connection,
                team_slug=team_slug,
                now=self._now(),
                limit=limit,
            )

    def reserve_eligible(self, team_slug: str, channel_id: int) -> int:
        now = self._now()
        fresh_after = now - timedelta(minutes=10)
        with self.connection_factory() as connection:
            candidates = self.repository.eligible_events(
                connection,
                team_slug=team_slug,
                now=now,
                fresh_after=fresh_after,
            )
        eligible_rows = tuple(
            event
            for event in candidates
            if event_date_is_current(
                event["start_datetime"],
                event["timezone"],
                now,
            )
        )
        events: dict[int, dict] = {}
        for row in eligible_rows:
            event_id = int(row["event_id"])
            event = events.setdefault(
                event_id,
                {
                    "event_id": event_id,
                    "event_name": str(row["event_name"]),
                    "source_url": str(row["source_url"]),
                    "end_datetime": row["end_datetime"],
                    "player_names": set(),
                },
            )
            event["player_names"].add(str(row["player_name"]))
        created = 0
        with self.transaction_factory() as connection:
            for event in events.values():
                player_names = tuple(event["player_names"])
                created += int(self.repository.reserve(
                    connection,
                    event_id=int(event["event_id"]),
                    channel_id=int(channel_id),
                    event_url=str(event["source_url"]),
                    message_content=format_live_event_message(
                        str(event["event_name"]),
                        player_names,
                        str(event["source_url"]),
                    ),
                    expires_at=event["end_datetime"],
                    now=now,
                ))
        return created

    def event_is_eligible(self, team_slug: str, event_id: int) -> bool:
        now = self._now()
        with self.connection_factory() as connection:
            events = self.repository.eligible_events(
                connection,
                team_slug=team_slug,
                now=now,
                fresh_after=now - timedelta(minutes=10),
            )
        return any(
            int(event["event_id"]) == int(event_id)
            and event_date_is_current(
                event["start_datetime"],
                event["timezone"],
                now,
            )
            for event in events
        )

    def next_pending(self) -> PendingAnnouncement | None:
        with self.connection_factory() as connection:
            row = self.repository.next_pending(connection, now=self._now())
        return None if row is None else PendingAnnouncement(**dict(row))

    def mark_sent(self, announcement_id: int, message_id: int) -> None:
        with self.transaction_factory() as connection:
            self.repository.mark_sent(
                connection,
                announcement_id=announcement_id,
                message_id=message_id,
                sent_at=self._now(),
            )

    def mark_failed(self, announcement: PendingAnnouncement, error: Exception) -> None:
        attempts = announcement.attempt_count + 1
        delay = min(60 * (2 ** min(attempts - 1, 6)), 3600)
        with self.transaction_factory() as connection:
            self.repository.mark_failed(
                connection,
                announcement_id=announcement.announcement_id,
                attempt_count=attempts,
                next_attempt_at=self._now() + timedelta(seconds=delay),
                error=f"{type(error).__name__}: {error}",
            )

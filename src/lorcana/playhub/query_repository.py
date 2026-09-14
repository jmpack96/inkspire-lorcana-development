"""Read-only PostgreSQL queries over Play Hub source and ingestion state."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Connection

from lorcana.db.schema.playhub import (
    playhub_events,
    playhub_import_attempts,
    playhub_matches,
    playhub_players,
    playhub_stores,
)


class PlayHubQueryRepository:
    def database_counts(self, connection: Connection) -> dict[str, int]:
        def count(table, condition=None) -> int:
            statement = select(func.count()).select_from(table)
            if condition is not None:
                statement = statement.where(condition)
            return int(connection.execute(statement).scalar_one())

        return {
            "events": count(playhub_events),
            "stores": count(playhub_stores),
            "players": count(playhub_players),
            "matches": count(playhub_matches),
            "two_player_matches": count(playhub_matches, playhub_matches.c.participant_count == 2),
            "multiplayer_matches": count(playhub_matches, playhub_matches.c.participant_count > 2),
            "unknown_participants": count(playhub_matches, playhub_matches.c.participant_count.is_(None)),
        }

    def latest_import(self, connection: Connection):
        return connection.execute(
            select(
                playhub_import_attempts.c.import_attempt_id,
                playhub_import_attempts.c.event_id,
                playhub_import_attempts.c.started_at,
                playhub_import_attempts.c.completed_at,
                playhub_import_attempts.c.status,
            )
            .order_by(
                playhub_import_attempts.c.started_at.desc(),
                playhub_import_attempts.c.import_attempt_id.desc(),
            )
            .limit(1)
        ).mappings().one_or_none()

    def find_set_championships(
        self,
        connection: Connection,
        *,
        set_name: str,
        city: str,
        state_values: Sequence[str],
        country_values: Sequence[str],
    ):
        short_name = f"%{set_name.strip().lower()} set champs%"
        long_name = f"%{set_name.strip().lower()} set championships%"
        city_value = city.strip().lower()
        state_values = [value.strip().upper() for value in state_values]
        country_values = [value.strip().upper() for value in country_values]
        statement = (
            select(
                playhub_events.c.event_id,
                playhub_events.c.name.label("event_name"),
                playhub_events.c.start_datetime,
                playhub_events.c.end_datetime,
                playhub_events.c.player_count,
                playhub_events.c.capacity,
                playhub_events.c.source_url,
                playhub_stores.c.store_id,
                playhub_stores.c.name.label("store_name"),
                playhub_stores.c.city,
                playhub_stores.c.state_region,
                playhub_stores.c.country,
                playhub_stores.c.latitude,
                playhub_stores.c.longitude,
            )
            .select_from(playhub_events.join(playhub_stores, playhub_stores.c.store_id == playhub_events.c.store_id))
            .where(func.lower(func.trim(playhub_stores.c.city)) == city_value)
            .where(func.upper(func.trim(playhub_stores.c.state_region)).in_(state_values))
            .where(func.upper(func.trim(playhub_stores.c.country)).in_(country_values))
            .where(or_(
                func.lower(playhub_events.c.name).like(short_name),
                func.lower(playhub_events.c.name).like(long_name),
            ))
            .order_by(playhub_events.c.start_datetime, playhub_stores.c.name, playhub_events.c.event_id)
        )
        return connection.execute(statement).mappings().all()

    def recent_event_player_rows(
        self,
        connection: Connection,
        *,
        player_ids: Sequence[int],
        start_at: datetime,
        end_at: datetime,
    ):
        if not player_ids:
            return []
        player1 = select(
            playhub_matches.c.event_id,
            playhub_matches.c.player1_id.label("player_id"),
        ).where(playhub_matches.c.player1_id.in_(list(player_ids)))
        player2 = select(
            playhub_matches.c.event_id,
            playhub_matches.c.player2_id.label("player_id"),
        ).where(playhub_matches.c.player2_id.in_(list(player_ids)))
        participants = player1.union(player2).subquery("team_event_players")
        statement = (
            select(
                playhub_events.c.event_id,
                playhub_events.c.name,
                playhub_events.c.start_datetime,
                playhub_events.c.format,
                playhub_events.c.source_url,
                participants.c.player_id,
            )
            .select_from(participants.join(playhub_events, playhub_events.c.event_id == participants.c.event_id))
            .where(playhub_events.c.start_datetime >= start_at)
            .where(playhub_events.c.start_datetime <= end_at)
            .order_by(
                playhub_events.c.start_datetime.desc(),
                playhub_events.c.event_id.desc(),
                participants.c.player_id,
            )
        )
        return connection.execute(statement).mappings().all()

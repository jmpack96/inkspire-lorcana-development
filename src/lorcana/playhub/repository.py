"""PostgreSQL persistence for Play Hub source facts and ingestion state."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from lorcana.db.schema.playhub import (
    playhub_discovery_runs,
    playhub_event_sync_state,
    playhub_events,
    playhub_import_attempts,
    playhub_matches,
    playhub_phases,
    playhub_players,
    playhub_registrations,
    playhub_rounds,
    playhub_stores,
)
from lorcana.playhub.types import (
    PlayHubEvent,
    PlayHubMatch,
    PlayHubPhase,
    PlayHubPlayer,
    PlayHubRegistration,
    PlayHubRound,
    PlayHubStore,
)


class PlayHubRepository:
    def upsert_store(self, connection: Connection, store: PlayHubStore) -> None:
        statement = insert(playhub_stores).values(**store.__dict__)
        statement = statement.on_conflict_do_update(
            index_elements=[playhub_stores.c.store_id],
            set_={
                "name": statement.excluded.name,
                "full_address": func.coalesce(statement.excluded.full_address, playhub_stores.c.full_address),
                "city": func.coalesce(statement.excluded.city, playhub_stores.c.city),
                "state_region": func.coalesce(statement.excluded.state_region, playhub_stores.c.state_region),
                "country": func.coalesce(statement.excluded.country, playhub_stores.c.country),
                "latitude": func.coalesce(statement.excluded.latitude, playhub_stores.c.latitude),
                "longitude": func.coalesce(statement.excluded.longitude, playhub_stores.c.longitude),
                "email": func.coalesce(statement.excluded.email, playhub_stores.c.email),
                "website": func.coalesce(statement.excluded.website, playhub_stores.c.website),
                "last_seen": statement.excluded.last_seen,
                "last_synced": statement.excluded.last_synced,
            },
        )
        connection.execute(statement)

    def upsert_event(self, connection: Connection, event: PlayHubEvent) -> None:
        statement = insert(playhub_events).values(**event.__dict__)
        optional_preserve = (
            "store_id", "start_datetime", "end_datetime", "timezone", "gameplay_format_id", "format",
            "event_format", "category", "display_status", "event_status", "lifecycle_status", "player_count",
            "registered_user_count", "capacity", "event_is_online", "full_address", "latitude", "longitude",
            "source_url",
        )
        values = {
            field: func.coalesce(getattr(statement.excluded, field), getattr(playhub_events.c, field))
            for field in optional_preserve
        }
        values.update({
            "name": statement.excluded.name,
            # First observation is historical provenance; never move it forward on refresh.
            "discovered_at": func.coalesce(playhub_events.c.discovered_at, statement.excluded.discovered_at),
            "last_synced": statement.excluded.last_synced,
        })
        statement = statement.on_conflict_do_update(
            index_elements=[playhub_events.c.event_id],
            set_=values,
        )
        connection.execute(statement)

    def upsert_phase(self, connection: Connection, phase: PlayHubPhase) -> None:
        statement = insert(playhub_phases).values(**phase.__dict__)
        statement = statement.on_conflict_do_update(
            index_elements=[playhub_phases.c.phase_id],
            set_={
                "event_id": statement.excluded.event_id,
                "phase_name": statement.excluded.phase_name,
                "phase_order": statement.excluded.phase_order,
                "round_type": statement.excluded.round_type,
                "status": statement.excluded.status,
            },
        )
        connection.execute(statement)

    def upsert_round(self, connection: Connection, round_record: PlayHubRound) -> None:
        values = {
            "round_id": round_record.round_id,
            "event_id": round_record.event_id,
            "phase_id": round_record.phase_id,
            "round_number": round_record.round_number,
            "round_type": round_record.round_type,
            "status": round_record.status,
            "pairings_status": round_record.pairings_status,
            "standings_status": round_record.standings_status,
            "final_round_in_event": round_record.final_round_in_event,
        }
        statement = insert(playhub_rounds).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[playhub_rounds.c.round_id],
            set_={field: getattr(statement.excluded, field) for field in values if field != "round_id"},
        )
        connection.execute(statement)

    def upsert_player(self, connection: Connection, player: PlayHubPlayer) -> None:
        statement = insert(playhub_players).values(**player.__dict__)
        statement = statement.on_conflict_do_update(
            index_elements=[playhub_players.c.player_id],
            set_={
                "display_name": func.coalesce(statement.excluded.display_name, playhub_players.c.display_name),
                "username": func.coalesce(statement.excluded.username, playhub_players.c.username),
                "first_seen": func.coalesce(playhub_players.c.first_seen, statement.excluded.first_seen),
                "last_seen": statement.excluded.last_seen,
            },
        )
        connection.execute(statement)

    def upsert_registration(self, connection: Connection, registration: PlayHubRegistration) -> None:
        statement = insert(playhub_registrations).values(**registration.__dict__)
        statement = statement.on_conflict_do_update(
            index_elements=[playhub_registrations.c.registration_id],
            set_={
                "event_id": statement.excluded.event_id,
                "player_id": statement.excluded.player_id,
                "display_name_at_event": statement.excluded.display_name_at_event,
                "registration_status": statement.excluded.registration_status,
                "matches_won": statement.excluded.matches_won,
                "matches_lost": statement.excluded.matches_lost,
                "matches_drawn": statement.excluded.matches_drawn,
                "match_points": statement.excluded.match_points,
                "placement": statement.excluded.placement,
                "registered_at": func.coalesce(statement.excluded.registered_at, playhub_registrations.c.registered_at),
                "last_synced": statement.excluded.last_synced,
            },
        )
        connection.execute(statement)

    def upsert_match(self, connection: Connection, match: PlayHubMatch) -> None:
        statement = insert(playhub_matches).values(**match.__dict__)
        statement = statement.on_conflict_do_update(
            index_elements=[playhub_matches.c.match_id],
            set_={
                field: getattr(statement.excluded, field)
                for field in match.__dict__
                if field != "match_id"
            },
        )
        connection.execute(statement)

    def get_player(self, connection: Connection, player_id: int) -> PlayHubPlayer | None:
        row = connection.execute(
            select(playhub_players).where(playhub_players.c.player_id == player_id)
        ).mappings().one_or_none()
        if row is None:
            return None
        return PlayHubPlayer(
            player_id=row["player_id"],
            display_name=row["display_name"],
            username=row["username"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
        )

    def has_completed_discovery_window(
        self,
        connection: Connection,
        *,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> bool:
        row = connection.execute(
            select(playhub_discovery_runs.c.discovery_run_id).where(
                playhub_discovery_runs.c.start_datetime == start_datetime,
                playhub_discovery_runs.c.end_datetime == end_datetime,
                playhub_discovery_runs.c.status == "complete",
            ).limit(1)
        ).first()
        return row is not None

    def start_discovery_run(
        self,
        connection: Connection,
        *,
        discovery_run_id: UUID,
        started_at: datetime,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> None:
        connection.execute(
            playhub_discovery_runs.insert().values(
                discovery_run_id=discovery_run_id,
                started_at=started_at,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                status="running",
            )
        )

    def finish_discovery_run(
        self,
        connection: Connection,
        *,
        discovery_run_id: UUID,
        completed_at: datetime,
        status: str,
        events_received: int,
        unique_events: int,
        duplicate_rows: int,
        error_category: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        connection.execute(
            update(playhub_discovery_runs)
            .where(playhub_discovery_runs.c.discovery_run_id == discovery_run_id)
            .values(
                completed_at=completed_at,
                status=status,
                events_received=events_received,
                unique_events=unique_events,
                duplicate_rows=duplicate_rows,
                error_category=error_category,
                error_summary=error_summary,
            )
        )

    def ensure_event_sync_state(
        self,
        connection: Connection,
        *,
        event_id: int,
        state: str = "discovered",
    ) -> None:
        statement = insert(playhub_event_sync_state).values(event_id=event_id, state=state)
        statement = statement.on_conflict_do_nothing(index_elements=[playhub_event_sync_state.c.event_id])
        connection.execute(statement)

    def start_import_attempt(
        self,
        connection: Connection,
        *,
        import_attempt_id: UUID,
        event_id: int,
        started_at: datetime,
    ) -> None:
        connection.execute(
            playhub_import_attempts.insert().values(
                import_attempt_id=import_attempt_id,
                event_id=event_id,
                started_at=started_at,
                status="running",
            )
        )

    def finish_import_attempt(
        self,
        connection: Connection,
        *,
        import_attempt_id: UUID,
        completed_at: datetime,
        status: str,
        rounds_expected: int,
        rounds_imported: int,
        registrations_found: int,
        matches_found: int,
        players_found: int,
        error_category: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        connection.execute(
            update(playhub_import_attempts)
            .where(playhub_import_attempts.c.import_attempt_id == import_attempt_id)
            .values(
                completed_at=completed_at,
                status=status,
                rounds_expected=rounds_expected,
                rounds_imported=rounds_imported,
                registrations_found=registrations_found,
                matches_found=matches_found,
                players_found=players_found,
                error_category=error_category,
                error_summary=error_summary,
            )
        )

    def set_event_sync_state(
        self,
        connection: Connection,
        *,
        event_id: int,
        state: str,
        last_attempt_at: datetime | None = None,
        last_success_at: datetime | None = None,
        last_error_category: str | None = None,
        last_error_summary: str | None = None,
        source_revision: str | None = None,
    ) -> None:
        statement = insert(playhub_event_sync_state).values(
            event_id=event_id,
            state=state,
            last_attempt_at=last_attempt_at,
            last_success_at=last_success_at,
            last_error_category=last_error_category,
            last_error_summary=last_error_summary,
            source_revision=source_revision,
        )
        # Preserve the most recent known success unless this call supplies a newer one.
        statement = statement.on_conflict_do_update(
            index_elements=[playhub_event_sync_state.c.event_id],
            set_={
                "state": statement.excluded.state,
                "last_attempt_at": func.coalesce(
                    statement.excluded.last_attempt_at, playhub_event_sync_state.c.last_attempt_at
                ),
                "last_success_at": func.coalesce(
                    statement.excluded.last_success_at, playhub_event_sync_state.c.last_success_at
                ),
                "last_error_category": statement.excluded.last_error_category,
                "last_error_summary": statement.excluded.last_error_summary,
                "source_revision": func.coalesce(
                    statement.excluded.source_revision, playhub_event_sync_state.c.source_revision
                ),
            },
        )
        connection.execute(statement)

    def due_event_import_ids(
        self,
        connection: Connection,
        *,
        now: datetime,
        lookback_start: datetime,
        retry_before: datetime,
        recent_complete_after: datetime,
        limit: int,
    ) -> tuple[int, ...]:
        active_source_statuses = ("LIVE", "ACTIVE", "RUNNING", "STARTED", "IN_PROGRESS")
        source_still_active = or_(
            *(
                func.upper(
                    func.replace(func.replace(func.trim(column), "-", "_"), " ", "_")
                ).in_(active_source_statuses)
                for column in (
                    playhub_events.c.display_status,
                    playhub_events.c.event_status,
                    playhub_events.c.lifecycle_status,
                )
            )
        )
        recently_active_or_ended = func.coalesce(
            playhub_events.c.end_datetime, playhub_events.c.start_datetime
        ) >= recent_complete_after
        final_import_cutoff = playhub_events.c.end_datetime + timedelta(hours=2)
        post_event_final_import_due = and_(
            playhub_events.c.end_datetime.is_not(None),
            final_import_cutoff <= now,
            or_(
                playhub_event_sync_state.c.last_attempt_at.is_(None),
                playhub_event_sync_state.c.last_attempt_at < final_import_cutoff,
            ),
        )
        rows = connection.execute(
            select(playhub_events.c.event_id)
            .select_from(
                playhub_events.join(
                    playhub_event_sync_state,
                    playhub_event_sync_state.c.event_id == playhub_events.c.event_id,
                )
            )
            .where(
                playhub_events.c.start_datetime.is_not(None),
                playhub_events.c.start_datetime >= lookback_start,
                playhub_events.c.start_datetime <= now,
                or_(
                    playhub_event_sync_state.c.state.in_(
                        ["discovered", "pending", "partial", "no_results", "failed"]
                    ),
                    and_(
                        playhub_event_sync_state.c.state == "complete",
                        recently_active_or_ended,
                        or_(source_still_active, post_event_final_import_due),
                    ),
                ),
                (
                    playhub_event_sync_state.c.last_attempt_at.is_(None)
                    | (playhub_event_sync_state.c.last_attempt_at <= retry_before)
                ),
            )
            .order_by(playhub_event_sync_state.c.last_attempt_at.asc().nullsfirst(),playhub_events.c.start_datetime,playhub_events.c.event_id,)
            .limit(limit)
        ).scalars().all()
        return tuple(int(value) for value in rows)

    def count_distinct_event_players(self, connection: Connection, event_id: int) -> int:
        player_ids = (
            select(playhub_registrations.c.player_id.label("player_id"))
            .where(playhub_registrations.c.event_id == event_id)
            .union(
                select(playhub_matches.c.player1_id.label("player_id")).where(
                    playhub_matches.c.event_id == event_id,
                    playhub_matches.c.player1_id.is_not(None),
                ),
                select(playhub_matches.c.player2_id.label("player_id")).where(
                    playhub_matches.c.event_id == event_id,
                    playhub_matches.c.player2_id.is_not(None),
                ),
            )
            .subquery()
        )
        return connection.execute(select(func.count()).select_from(player_ids)).scalar_one()

"""PostgreSQL persistence and source queries for rating runs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from lorcana.db.schema.playhub import (
    playhub_event_sync_state,
    playhub_events,
    playhub_matches,
    playhub_phases,
    playhub_players,
    playhub_registrations,
    playhub_rounds,
)
from lorcana.db.schema.ratings import (
    rating_current,
    rating_history,
    rating_publications,
    rating_run_inputs,
    rating_runs,
)
from lorcana.ratings.types import RatingCandidate, RatingRunInput


class RatingRepository:
    def create_run(
        self,
        connection: Connection,
        *,
        rating_run_id: UUID,
        algorithm: str,
        algorithm_version: str,
        policy_version: str,
        parameters: Mapping[str, Any],
        started_at: datetime,
        notes: str | None = None,
    ) -> None:
        connection.execute(
            rating_runs.insert().values(
                rating_run_id=rating_run_id,
                algorithm=algorithm,
                algorithm_version=algorithm_version,
                policy_version=policy_version,
                parameters=dict(parameters),
                started_at=started_at,
                status="building",
                notes=notes,
            )
        )

    def iter_candidates(self, connection: Connection) -> Iterator[RatingCandidate]:
        phase_order = func.coalesce(playhub_phases.c.phase_order, 0)
        round_number = func.coalesce(playhub_rounds.c.round_number, 0)
        statement = (
            select(
                playhub_matches.c.match_id,
                playhub_matches.c.event_id,
                playhub_matches.c.round_id,
                playhub_matches.c.player1_id,
                playhub_matches.c.player2_id,
                playhub_matches.c.winner_id,
                playhub_matches.c.is_draw,
                playhub_matches.c.status.label("match_status"),
                playhub_matches.c.is_bye,
                playhub_matches.c.is_ghost_match,
                playhub_matches.c.participant_count,
                playhub_events.c.start_datetime.label("event_start_datetime"),
                playhub_events.c.format.label("event_format"),
                playhub_event_sync_state.c.state.label("event_sync_state"),
                phase_order.label("phase_order"),
                round_number.label("round_number"),
            )
            .select_from(
                playhub_matches.join(
                    playhub_events, playhub_events.c.event_id == playhub_matches.c.event_id
                )
                .outerjoin(playhub_rounds, playhub_rounds.c.round_id == playhub_matches.c.round_id)
                .outerjoin(playhub_phases, playhub_phases.c.phase_id == playhub_rounds.c.phase_id)
                .outerjoin(
                    playhub_event_sync_state,
                    playhub_event_sync_state.c.event_id == playhub_events.c.event_id,
                )
            )
            .order_by(
                playhub_events.c.start_datetime,
                playhub_matches.c.event_id,
                phase_order,
                round_number,
                playhub_matches.c.match_id,
            )
        )
        result = connection.execution_options(stream_results=True).execute(statement).mappings()
        for row in result:
            yield RatingCandidate(**dict(row))

    def insert_run_inputs(
        self,
        connection: Connection,
        rating_run_id: UUID,
        inputs: Sequence[RatingRunInput],
    ) -> None:
        if not inputs:
            return
        connection.execute(
            rating_run_inputs.insert(),
            [
                {
                    "rating_run_id": rating_run_id,
                    "sequence_number": row.sequence_number,
                    "match_id": row.match_id,
                    "event_id": row.event_id,
                    "event_start_datetime": row.event_start_datetime,
                    "phase_order": row.phase_order,
                    "round_number": row.round_number,
                    "player1_id": row.player1_id,
                    "player2_id": row.player2_id,
                    "winner_id": row.winner_id,
                    "is_draw": row.is_draw,
                }
                for row in inputs
            ],
        )

    def finish_snapshot(
        self,
        connection: Connection,
        *,
        rating_run_id: UUID,
        input_count: int,
        ordered_input_digest: str,
        exclusion_counts: Mapping[str, int],
    ) -> None:
        connection.execute(
            update(rating_runs)
            .where(rating_runs.c.rating_run_id == rating_run_id)
            .values(
                input_count=input_count,
                ordered_input_digest=ordered_input_digest,
                exclusion_counts=dict(exclusion_counts),
            )
        )

    def iter_run_inputs(self, connection: Connection, rating_run_id: UUID) -> Iterator[RatingRunInput]:
        statement = (
            select(
                rating_run_inputs.c.sequence_number,
                rating_run_inputs.c.match_id,
                rating_run_inputs.c.event_id,
                rating_run_inputs.c.event_start_datetime,
                rating_run_inputs.c.phase_order,
                rating_run_inputs.c.round_number,
                rating_run_inputs.c.player1_id,
                rating_run_inputs.c.player2_id,
                rating_run_inputs.c.winner_id,
                rating_run_inputs.c.is_draw,
            )
            .where(rating_run_inputs.c.rating_run_id == rating_run_id)
            .order_by(rating_run_inputs.c.sequence_number)
        )
        for row in connection.execution_options(stream_results=True).execute(statement).mappings():
            yield RatingRunInput(**dict(row))

    def insert_history(self, connection: Connection, rows: Sequence[Mapping[str, Any]]) -> None:
        if rows:
            connection.execute(rating_history.insert(), list(rows))

    def insert_current(self, connection: Connection, rows: Sequence[Mapping[str, Any]]) -> None:
        if rows:
            connection.execute(rating_current.insert(), list(rows))

    def count_history(self, connection: Connection, rating_run_id: UUID) -> int:
        return connection.execute(
            select(func.count()).select_from(rating_history).where(rating_history.c.rating_run_id == rating_run_id)
        ).scalar_one()

    def count_current(self, connection: Connection, rating_run_id: UUID) -> int:
        return connection.execute(
            select(func.count()).select_from(rating_current).where(rating_current.c.rating_run_id == rating_run_id)
        ).scalar_one()

    def mark_validated(
        self,
        connection: Connection,
        *,
        rating_run_id: UUID,
        completed_at: datetime,
        player_count: int,
    ) -> None:
        connection.execute(
            update(rating_runs)
            .where(rating_runs.c.rating_run_id == rating_run_id)
            .values(status="validated", completed_at=completed_at, player_count=player_count)
        )

    def mark_failed(
        self,
        connection: Connection,
        *,
        rating_run_id: UUID,
        completed_at: datetime,
        notes: str,
    ) -> None:
        connection.execute(
            update(rating_runs)
            .where(rating_runs.c.rating_run_id == rating_run_id)
            .values(status="failed", completed_at=completed_at, notes=notes)
        )

    def get_run_status(
        self,
        connection: Connection,
        rating_run_id: UUID,
        *,
        for_update: bool = False,
    ) -> str | None:
        statement = select(rating_runs.c.status).where(rating_runs.c.rating_run_id == rating_run_id)
        if for_update:
            statement = statement.with_for_update()
        return connection.execute(statement).scalar_one_or_none()

    def publish(
        self,
        connection: Connection,
        *,
        publication_name: str,
        rating_run_id: UUID,
        published_at: datetime,
        published_by: str | None,
    ) -> UUID | None:
        """Rotate a publication pointer and return the previous current run.

        Publication rows explicitly remember two generations: current and
        immediately previous. Republishing the current run is idempotent and
        does not disturb the previous pointer.
        """
        existing = connection.execute(
            select(
                rating_publications.c.rating_run_id,
                rating_publications.c.previous_rating_run_id,
            )
            .where(rating_publications.c.publication_name == publication_name)
            .with_for_update()
        ).mappings().one_or_none()

        previous_current: UUID | None = None
        if existing is None:
            connection.execute(
                rating_publications.insert().values(
                    publication_name=publication_name,
                    rating_run_id=rating_run_id,
                    previous_rating_run_id=None,
                    published_at=published_at,
                    published_by=published_by,
                )
            )
        elif existing["rating_run_id"] == rating_run_id:
            # Idempotent republish: only publication metadata changes.
            connection.execute(
                update(rating_publications)
                .where(rating_publications.c.publication_name == publication_name)
                .values(published_at=published_at, published_by=published_by)
            )
        else:
            previous_current = existing["rating_run_id"]
            connection.execute(
                update(rating_publications)
                .where(rating_publications.c.publication_name == publication_name)
                .values(
                    rating_run_id=rating_run_id,
                    previous_rating_run_id=previous_current,
                    published_at=published_at,
                    published_by=published_by,
                )
            )

        connection.execute(
            update(rating_runs)
            .where(rating_runs.c.rating_run_id == rating_run_id)
            .values(status="published")
        )
        return previous_current

    def retained_run_ids(self, connection: Connection) -> set[UUID]:
        """Return every run protected by a current/previous publication slot."""
        rows = connection.execute(
            select(
                rating_publications.c.rating_run_id,
                rating_publications.c.previous_rating_run_id,
            )
        ).all()
        retained: set[UUID] = set()
        for current_id, previous_id in rows:
            retained.add(current_id)
            if previous_id is not None:
                retained.add(previous_id)
        return retained

    def prune_unretained_runs(self, connection: Connection) -> tuple[UUID, ...]:
        """Delete all non-building rating runs not protected by a publication.

        A run currently being calculated is transient and must never be deleted
        by another publisher. All completed abandoned/failed/superseded runs are
        eligible for pruning. Children are deleted explicitly because the schema
        intentionally does not rely on cascading deletes for source-linked data.
        """
        retained = self.retained_run_ids(connection)
        candidate = select(rating_runs.c.rating_run_id).where(
            rating_runs.c.status != "building"
        )
        if retained:
            candidate = candidate.where(rating_runs.c.rating_run_id.not_in(retained))
        doomed = tuple(connection.execute(candidate).scalars().all())
        if not doomed:
            return ()

        connection.execute(
            delete(rating_history).where(rating_history.c.rating_run_id.in_(doomed))
        )
        connection.execute(
            delete(rating_current).where(rating_current.c.rating_run_id.in_(doomed))
        )
        connection.execute(
            delete(rating_run_inputs).where(rating_run_inputs.c.rating_run_id.in_(doomed))
        )
        connection.execute(
            delete(rating_runs).where(rating_runs.c.rating_run_id.in_(doomed))
        )
        return doomed
    def resolve_publication(self, connection: Connection, publication_name: str):
        statement = (
            select(
                rating_publications.c.publication_name,
                rating_publications.c.rating_run_id,
                rating_publications.c.published_at,
                rating_publications.c.previous_rating_run_id,
                rating_runs.c.algorithm,
                rating_runs.c.algorithm_version,
                rating_runs.c.policy_version,
                rating_runs.c.parameters,
                rating_runs.c.input_count,
                rating_runs.c.player_count,
                rating_runs.c.ordered_input_digest,
                rating_runs.c.exclusion_counts,
            )
            .select_from(
                rating_publications.join(
                    rating_runs,
                    rating_runs.c.rating_run_id == rating_publications.c.rating_run_id,
                )
            )
            .where(rating_publications.c.publication_name == publication_name)
        )
        return connection.execute(statement).mappings().one_or_none()

    @staticmethod
    def _ranked_current(rating_run_id: UUID):
        return (
            select(
                rating_current.c.player_id,
                rating_current.c.rating,
                rating_current.c.matches_played,
                rating_current.c.wins,
                rating_current.c.losses,
                rating_current.c.draws,
                rating_current.c.peak_rating,
                func.row_number().over(
                    order_by=(
                        rating_current.c.rating.desc(),
                        rating_current.c.matches_played.desc(),
                        rating_current.c.player_id.asc(),
                    )
                ).label("rank"),
            )
            .where(rating_current.c.rating_run_id == rating_run_id)
            .subquery("ranked_rating_current")
        )

    def leaderboard(
        self,
        connection: Connection,
        rating_run_id: UUID,
        *,
        limit: int,
        offset: int,
    ):
        ranked = self._ranked_current(rating_run_id)
        statement = (
            select(
                ranked.c.rank,
                ranked.c.player_id,
                playhub_players.c.display_name,
                playhub_players.c.username,
                ranked.c.rating,
                ranked.c.matches_played,
                ranked.c.wins,
                ranked.c.losses,
                ranked.c.draws,
                ranked.c.peak_rating,
            )
            .select_from(
                ranked.outerjoin(
                    playhub_players,
                    playhub_players.c.player_id == ranked.c.player_id,
                )
            )
            .order_by(ranked.c.rank)
            .limit(limit)
            .offset(offset)
        )
        return connection.execute(statement).mappings().all()

    def player_rating(self, connection: Connection, rating_run_id: UUID, player_id: int):
        ranked = self._ranked_current(rating_run_id)
        statement = (
            select(
                ranked.c.rank,
                ranked.c.player_id,
                playhub_players.c.display_name,
                playhub_players.c.username,
                ranked.c.rating,
                ranked.c.matches_played,
                ranked.c.wins,
                ranked.c.losses,
                ranked.c.draws,
                ranked.c.peak_rating,
            )
            .select_from(
                ranked.outerjoin(
                    playhub_players,
                    playhub_players.c.player_id == ranked.c.player_id,
                )
            )
            .where(ranked.c.player_id == player_id)
        )
        return connection.execute(statement).mappings().one_or_none()
    def search_players(
        self,
        connection: Connection,
        rating_run_id: UUID,
        query: str,
        *,
        limit: int = 10,
    ):
        current_join = and_(
            rating_current.c.player_id == playhub_players.c.player_id,
            rating_current.c.rating_run_id == rating_run_id,
        )
        statement = select(
            playhub_players.c.player_id,
            playhub_players.c.display_name,
            playhub_players.c.username,
            rating_current.c.rating,
            rating_current.c.matches_played,
        ).select_from(playhub_players.outerjoin(rating_current, current_join))
        stripped = query.strip()
        if stripped.isdigit():
            statement = statement.where(playhub_players.c.player_id == int(stripped))
        else:
            exact = stripped.lower()
            pattern = f"%{exact}%"
            display = func.lower(func.coalesce(playhub_players.c.display_name, ""))
            username = func.lower(func.coalesce(playhub_players.c.username, ""))
            statement = (
                statement
                .where((display.like(pattern)) | (username.like(pattern)))
                .order_by(
                    case((display == exact, 0), (username == exact, 1), else_=2),
                    rating_current.c.rating.desc().nulls_last(),
                    playhub_players.c.player_id,
                )
                .limit(limit)
            )
        return connection.execute(statement).mappings().all()

    def source_player(self, connection: Connection, player_id: int):
        return connection.execute(
            select(
                playhub_players.c.player_id,
                playhub_players.c.display_name,
                playhub_players.c.username,
            ).where(playhub_players.c.player_id == player_id)
        ).mappings().one_or_none()

    def player_current_raw(self, connection: Connection, rating_run_id: UUID, player_id: int):
        return connection.execute(
            select(
                rating_current.c.rating,
                rating_current.c.matches_played,
                rating_current.c.wins,
                rating_current.c.losses,
                rating_current.c.draws,
                rating_current.c.peak_rating,
            )
            .where(rating_current.c.rating_run_id == rating_run_id)
            .where(rating_current.c.player_id == player_id)
        ).mappings().one_or_none()

    def player_rank_stats(
        self, connection: Connection, rating_run_id: UUID, rating: float
    ) -> tuple[int, int, int]:
        total = connection.execute(
            select(func.count()).select_from(rating_current).where(
                rating_current.c.rating_run_id == rating_run_id
            )
        ).scalar_one()
        above = connection.execute(
            select(func.count()).select_from(rating_current).where(
                rating_current.c.rating_run_id == rating_run_id,
                rating_current.c.rating > rating,
            )
        ).scalar_one()
        below = connection.execute(
            select(func.count()).select_from(rating_current).where(
                rating_current.c.rating_run_id == rating_run_id,
                rating_current.c.rating < rating,
            )
        ).scalar_one()
        return int(total), int(above), int(below)

    def player_tournament_history(
        self,
        connection: Connection,
        rating_run_id: UUID,
        player_id: int,
    ):
        opponent = playhub_players.alias("history_opponent")
        registration = playhub_registrations.alias("history_registration")
        run_input = rating_run_inputs.alias("history_rating_input")

        opponent_id = case(
            (
                playhub_matches.c.player1_id == player_id,
                playhub_matches.c.player2_id,
            ),
            else_=playhub_matches.c.player1_id,
        )

        player_score = case(
            (
                playhub_matches.c.player1_id == player_id,
                playhub_matches.c.player1_score,
            ),
            else_=playhub_matches.c.player2_score,
        )

        opponent_score = case(
            (
                playhub_matches.c.player1_id == player_id,
                playhub_matches.c.player2_score,
            ),
            else_=playhub_matches.c.player1_score,
        )

        statement = (
            select(
                playhub_events.c.event_id,
                playhub_events.c.name.label("event_name"),
                playhub_events.c.start_datetime,
                playhub_events.c.format.label("event_format"),
                playhub_events.c.source_url,

                registration.c.matches_won,
                registration.c.matches_lost,
                registration.c.matches_drawn,
                registration.c.placement,

                playhub_matches.c.match_id,
                playhub_matches.c.winner_id,
                playhub_matches.c.is_draw,
                playhub_matches.c.is_intentional_draw,
                playhub_matches.c.is_bye,

                player_score.label("player_score"),
                opponent_score.label("opponent_score"),

                playhub_rounds.c.round_number,
                playhub_phases.c.phase_name,

                opponent_id.label("opponent_id"),
                opponent.c.display_name.label("opponent_name"),
                opponent.c.username.label("opponent_username"),

                run_input.c.match_id.is_not(None).label("rated"),
            )
            .select_from(
                playhub_matches
                .join(
                    playhub_events,
                    playhub_events.c.event_id == playhub_matches.c.event_id,
                )
                .outerjoin(
                    playhub_rounds,
                    playhub_rounds.c.round_id == playhub_matches.c.round_id,
                )
                .outerjoin(
                    playhub_phases,
                    playhub_phases.c.phase_id == playhub_rounds.c.phase_id,
                )
                .outerjoin(
                    registration,
                    and_(
                        registration.c.event_id == playhub_matches.c.event_id,
                        registration.c.player_id == player_id,
                    ),
                )
                .outerjoin(
                    opponent,
                    opponent.c.player_id == opponent_id,
                )
                .outerjoin(
                    run_input,
                    and_(
                        run_input.c.rating_run_id == rating_run_id,
                        run_input.c.match_id == playhub_matches.c.match_id,
                    ),
                )
            )
            .where(
                (playhub_matches.c.player1_id == player_id)
                | (playhub_matches.c.player2_id == player_id)
            )
            .order_by(
                playhub_events.c.start_datetime.desc().nulls_last(),
                playhub_events.c.event_id.desc(),
                func.coalesce(playhub_phases.c.phase_order, 0),
                func.coalesce(playhub_rounds.c.round_number, 0),
                playhub_matches.c.match_id,
            )
        )

        return connection.execute(statement).mappings().all()

    def player_history(self, connection: Connection, rating_run_id: UUID, player_id: int):
        return connection.execute(
            select(
                rating_history.c.rating_before,
                rating_history.c.rating_after,
                rating_history.c.rating_change,
                rating_history.c.opponent_id,
                rating_history.c.opponent_rating_before,
                rating_history.c.result,
                rating_history.c.event_id,
                rating_history.c.sequence_number,
            )
            .where(rating_history.c.rating_run_id == rating_run_id)
            .where(rating_history.c.player_id == player_id)
            .order_by(rating_history.c.sequence_number.desc())
        ).mappings().all()

    def best_win(self, connection: Connection, rating_run_id: UUID, player_id: int):
        opponent = playhub_players.alias("best_win_opponent")
        statement = (
            select(
                rating_history.c.opponent_id,
                rating_history.c.opponent_rating_before.label("opponent_rating"),
                rating_history.c.rating_change,
                opponent.c.display_name.label("opponent_name"),
                opponent.c.username.label("opponent_username"),
                playhub_events.c.name.label("event_name"),
                playhub_events.c.start_datetime.label("event_date"),
            )
            .select_from(
                rating_history
                .outerjoin(opponent, opponent.c.player_id == rating_history.c.opponent_id)
                .outerjoin(playhub_events, playhub_events.c.event_id == rating_history.c.event_id)
            )
            .where(rating_history.c.rating_run_id == rating_run_id)
            .where(rating_history.c.player_id == player_id)
            .where(rating_history.c.result == "WIN")
            .order_by(
                rating_history.c.opponent_rating_before.desc(),
                rating_history.c.rating_change.desc(),
            )
            .limit(1)
        )
        return connection.execute(statement).mappings().one_or_none()

    def leaderboard_filtered(
        self,
        connection: Connection,
        rating_run_id: UUID,
        *,
        minimum_matches: int,
        limit: int,
    ):
        eligible = (
            select(
                rating_current.c.player_id,
                rating_current.c.rating,
                rating_current.c.matches_played,
                rating_current.c.wins,
                rating_current.c.losses,
                rating_current.c.draws,
                rating_current.c.peak_rating,
                func.row_number().over(
                    order_by=(
                        rating_current.c.rating.desc(),
                        rating_current.c.matches_played.desc(),
                        rating_current.c.player_id.asc(),
                    )
                ).label("rank"),
            )
            .where(rating_current.c.rating_run_id == rating_run_id)
            .where(rating_current.c.matches_played >= minimum_matches)
            .subquery("eligible_rating_current")
        )
        statement = (
            select(
                eligible.c.rank, eligible.c.player_id,
                playhub_players.c.display_name, playhub_players.c.username,
                eligible.c.rating, eligible.c.matches_played, eligible.c.wins,
                eligible.c.losses, eligible.c.draws, eligible.c.peak_rating,
            )
            .select_from(eligible.outerjoin(
                playhub_players, playhub_players.c.player_id == eligible.c.player_id
            ))
            .order_by(eligible.c.rank)
            .limit(limit)
        )
        return connection.execute(statement).mappings().all()

    def eligible_player_count(
        self, connection: Connection, rating_run_id: UUID, minimum_matches: int
    ) -> int:
        return int(connection.execute(
            select(func.count()).select_from(rating_current).where(
                rating_current.c.rating_run_id == rating_run_id,
                rating_current.c.matches_played >= minimum_matches,
            )
        ).scalar_one())

    def current_for_players(
        self, connection: Connection, rating_run_id: UUID, player_ids: Sequence[int]
    ):
        if not player_ids:
            return []
        return connection.execute(
            select(
                rating_current.c.player_id, rating_current.c.rating,
                rating_current.c.matches_played, rating_current.c.wins,
                rating_current.c.losses, rating_current.c.draws, rating_current.c.peak_rating,
            )
            .where(rating_current.c.rating_run_id == rating_run_id)
            .where(rating_current.c.player_id.in_(list(player_ids)))
        ).mappings().all()


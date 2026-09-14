"""Read models for consumers of published rating runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ContextManager
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.engine import Connection, Engine

from lorcana.ratings.elo import expected_score
from lorcana.ratings.repository import RatingRepository

ConnectionFactory = Callable[[], ContextManager[Connection]]


class RatingPublicationNotFound(LookupError):
    pass


@dataclass(frozen=True)
class PublishedRatingRun:
    publication_name: str
    rating_run_id: UUID
    published_at: datetime
    algorithm: str
    algorithm_version: str
    policy_version: str
    input_count: int
    player_count: int
    ordered_input_digest: str
    previous_rating_run_id: UUID | None = None


@dataclass(frozen=True)
class LeaderboardEntry:
    rank: int
    player_id: int
    display_name: str | None
    username: str | None
    rating: float
    matches_played: int
    wins: int
    losses: int
    draws: int
    peak_rating: float


@dataclass(frozen=True)
class PublishedLeaderboard:
    publication: PublishedRatingRun
    entries: tuple[LeaderboardEntry, ...]
    eligible_players: int | None = None
    minimum_matches: int | None = None


@dataclass(frozen=True)
class PublishedPlayerRating:
    publication: PublishedRatingRun
    player: LeaderboardEntry | None


@dataclass(frozen=True)
class PlayerSearchResult:
    player_id: int
    display_name: str | None
    username: str | None
    rating: float | None
    matches_played: int | None


@dataclass(frozen=True)
class RecordSummary:
    wins: int
    losses: int
    draws: int


@dataclass(frozen=True)
class BestWin:
    opponent_id: int
    opponent_rating: float
    rating_change: float
    opponent_name: str | None
    opponent_username: str | None
    event_name: str | None
    event_date: datetime | None


@dataclass(frozen=True)
class PlayerProfile:
    publication: PublishedRatingRun
    player_id: int
    display_name: str | None
    username: str | None
    has_rating: bool
    rating: float | None = None
    peak_rating: float | None = None
    matches_played: int | None = None
    wins: int | None = None
    losses: int | None = None
    draws: int | None = None
    rank: int | None = None
    total_rated: int | None = None
    percentile: float | None = None
    recent_10: RecordSummary | None = None
    recent_25: RecordSummary | None = None
    rating_change_25: float | None = None
    average_opponent_rating: float | None = None
    expected_score_total: float | None = None
    actual_score_total: float | None = None
    performance_vs_expected: float | None = None
    best_win: BestWin | None = None


def _record(rows) -> RecordSummary:
    results = [row["result"] for row in rows]
    return RecordSummary(
        wins=results.count("WIN"),
        losses=results.count("LOSS"),
        draws=results.count("DRAW"),
    )


class RatingQueryService:
    """Resolve a publication once, then query only that immutable run."""

    def __init__(self, *, repository: RatingRepository, connection_factory: ConnectionFactory) -> None:
        self.repository = repository
        self.connection_factory = connection_factory

    @classmethod
    def from_engine(
        cls,
        engine: Engine,
        *,
        repository: RatingRepository | None = None,
    ) -> "RatingQueryService":
        return cls(repository=repository or RatingRepository(), connection_factory=engine.connect)

    def leaderboard(
        self,
        *,
        publication_name: str = "global_elo",
        limit: int = 25,
        offset: int = 0,
    ) -> PublishedLeaderboard:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        with self.connection_factory() as connection:
            publication = self._resolve(connection, publication_name)
            rows = self.repository.leaderboard(
                connection,
                publication.rating_run_id,
                limit=limit,
                offset=offset,
            )
        return PublishedLeaderboard(
            publication=publication,
            entries=tuple(LeaderboardEntry(**dict(row)) for row in rows),
        )

    def competitive_leaderboard(
        self,
        *,
        publication_name: str = "global_elo",
        minimum_matches: int = 20,
        limit: int = 25,
    ) -> PublishedLeaderboard:
        if not 1 <= minimum_matches <= 100_000:
            raise ValueError("minimum_matches must be positive")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self.connection_factory() as connection:
            publication = self._resolve(connection, publication_name)
            rows = self.repository.leaderboard_filtered(
                connection,
                publication.rating_run_id,
                minimum_matches=minimum_matches,
                limit=limit,
            )
            eligible = self.repository.eligible_player_count(
                connection, publication.rating_run_id, minimum_matches
            )
        return PublishedLeaderboard(
            publication=publication,
            entries=tuple(LeaderboardEntry(**dict(row)) for row in rows),
            eligible_players=eligible,
            minimum_matches=minimum_matches,
        )

    def player_by_id(
        self,
        player_id: int,
        *,
        publication_name: str = "global_elo",
    ) -> PublishedPlayerRating:
        with self.connection_factory() as connection:
            publication = self._resolve(connection, publication_name)
            row = self.repository.player_rating(connection, publication.rating_run_id, player_id)
        return PublishedPlayerRating(
            publication=publication,
            player=None if row is None else LeaderboardEntry(**dict(row)),
        )

    def search_players(
        self,
        query: str,
        *,
        publication_name: str = "global_elo",
        limit: int = 10,
    ) -> tuple[PlayerSearchResult, ...]:
        if not query.strip():
            raise ValueError("player query must not be empty")
        if not 1 <= limit <= 25:
            raise ValueError("search limit must be between 1 and 25")
        with self.connection_factory() as connection:
            publication = self._resolve(connection, publication_name)
            rows = self.repository.search_players(
                connection, publication.rating_run_id, query, limit=limit
            )
        return tuple(PlayerSearchResult(**dict(row)) for row in rows)

    def player_profile(
        self,
        player_id: int,
        *,
        publication_name: str = "global_elo",
    ) -> PlayerProfile | None:
        with self.connection_factory() as connection:
            publication = self._resolve(connection, publication_name)
            source = self.repository.source_player(connection, player_id)
            if source is None:
                return None
            current = self.repository.player_current_raw(
                connection, publication.rating_run_id, player_id
            )
            if current is None:
                return PlayerProfile(
                    publication=publication,
                    player_id=source["player_id"],
                    display_name=source["display_name"],
                    username=source["username"],
                    has_rating=False,
                )

            total, above, below = self.repository.player_rank_stats(
                connection, publication.rating_run_id, current["rating"]
            )
            history = self.repository.player_history(
                connection, publication.rating_run_id, player_id
            )
            best = self.repository.best_win(
                connection, publication.rating_run_id, player_id
            )

        recent_10_rows = history[:10]
        recent_25_rows = history[:25]
        opponent_ratings = [
            row["opponent_rating_before"]
            for row in history
            if row["opponent_rating_before"] is not None
        ]
        expected_total = sum(
            expected_score(row["rating_before"], row["opponent_rating_before"])
            for row in history
            if row["opponent_rating_before"] is not None
        )
        actual_total = sum(
            1.0 if row["result"] == "WIN" else 0.5 if row["result"] == "DRAW" else 0.0
            for row in history
        )
        percentile = 100.0 if total <= 1 else below / (total - 1) * 100.0
        best_win = None if best is None else BestWin(**dict(best))
        return PlayerProfile(
            publication=publication,
            player_id=source["player_id"],
            display_name=source["display_name"],
            username=source["username"],
            has_rating=True,
            rating=current["rating"],
            peak_rating=current["peak_rating"],
            matches_played=current["matches_played"],
            wins=current["wins"],
            losses=current["losses"],
            draws=current["draws"],
            rank=above + 1,
            total_rated=total,
            percentile=percentile,
            recent_10=_record(recent_10_rows),
            recent_25=_record(recent_25_rows),
            rating_change_25=sum(row["rating_change"] for row in recent_25_rows),
            average_opponent_rating=(
                sum(opponent_ratings) / len(opponent_ratings) if opponent_ratings else None
            ),
            expected_score_total=expected_total,
            actual_score_total=actual_total,
            performance_vs_expected=actual_total - expected_total,
            best_win=best_win,
        )

    def _resolve(self, connection: Connection, publication_name: str) -> PublishedRatingRun:
        row = self.repository.resolve_publication(connection, publication_name)
        if row is None:
            raise RatingPublicationNotFound(f"No published rating run named {publication_name!r}")
        return PublishedRatingRun(**dict(row))

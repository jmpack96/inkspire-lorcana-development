"""Read models combining team identity with a published rating run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ContextManager
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.engine import Connection, Engine

from lorcana.playhub.query_service import PlayHubQueryService, TeamEvent
from lorcana.ratings.query_service import PublishedRatingRun, RatingPublicationNotFound
from lorcana.ratings.repository import RatingRepository
from lorcana.teams.repository import TeamRepository

ConnectionFactory = Callable[[], ContextManager[Connection]]


class TeamNotFound(LookupError):
    pass


@dataclass(frozen=True)
class TeamLeaderboardMember:
    team_rank: int | None
    member_id: UUID
    preferred_display_name: str
    playhub_player_id: int | None
    role: str
    rating: float | None
    matches_played: int | None
    wins: int | None
    losses: int | None
    draws: int | None
    peak_rating: float | None


@dataclass(frozen=True)
class TeamLeaderboard:
    team_id: UUID
    team_slug: str
    team_name: str
    publication: PublishedRatingRun
    members: tuple[TeamLeaderboardMember, ...]
    recent_events: tuple[TeamEvent, ...]
    recent_event_days: int


class TeamQueryService:
    def __init__(
        self,
        *,
        team_repository: TeamRepository,
        rating_repository: RatingRepository,
        playhub_queries: PlayHubQueryService,
        connection_factory: ConnectionFactory,
    ) -> None:
        self.team_repository = team_repository
        self.rating_repository = rating_repository
        self.playhub_queries = playhub_queries
        self.connection_factory = connection_factory

    @classmethod
    def from_engine(cls, engine: Engine) -> "TeamQueryService":
        return cls(
            team_repository=TeamRepository(),
            rating_repository=RatingRepository(),
            playhub_queries=PlayHubQueryService.from_engine(engine),
            connection_factory=engine.connect,
        )

    def leaderboard(
        self,
        slug: str,
        *,
        publication_name: str = "global_elo",
        recent_event_days: int = 7,
        now: datetime | None = None,
    ) -> TeamLeaderboard:
        with self.connection_factory() as connection:
            team = self.team_repository.team_identity(connection, slug)
            if team is None:
                raise TeamNotFound(f"Unknown active team {slug!r}")
            members = self.team_repository.active_members(connection, slug)
            publication_row = self.rating_repository.resolve_publication(connection, publication_name)
            if publication_row is None:
                raise RatingPublicationNotFound(f"No published rating run named {publication_name!r}")
            publication = PublishedRatingRun(**dict(publication_row))
            player_ids = [m.playhub_player_id for m in members if m.playhub_player_id is not None]
            current_rows = self.rating_repository.current_for_players(
                connection, publication.rating_run_id, player_ids
            )

        current = {row["player_id"]: row for row in current_rows}
        combined = []
        for member in members:
            row = current.get(member.playhub_player_id)
            combined.append((member, row))
        combined.sort(
            key=lambda item: (
                item[1] is None,
                -(item[1]["rating"] if item[1] is not None else 0.0),
                -(item[1]["matches_played"] if item[1] is not None else 0),
                item[0].playhub_player_id or 0,
            )
        )
        output: list[TeamLeaderboardMember] = []
        rated_rank = 0
        for member, row in combined:
            if row is not None:
                rated_rank += 1
            output.append(
                TeamLeaderboardMember(
                    team_rank=rated_rank if row is not None else None,
                    member_id=member.member_id,
                    preferred_display_name=member.preferred_display_name,
                    playhub_player_id=member.playhub_player_id,
                    role=member.role,
                    rating=None if row is None else row["rating"],
                    matches_played=None if row is None else row["matches_played"],
                    wins=None if row is None else row["wins"],
                    losses=None if row is None else row["losses"],
                    draws=None if row is None else row["draws"],
                    peak_rating=None if row is None else row["peak_rating"],
                )
            )
        recent_events = self.playhub_queries.recent_events_for_players(
            player_ids, days=recent_event_days, now=now
        )
        return TeamLeaderboard(
            team_id=team["team_id"],
            team_slug=team["slug"],
            team_name=team["name"],
            publication=publication,
            members=tuple(output),
            recent_events=recent_events,
            recent_event_days=recent_event_days,
        )

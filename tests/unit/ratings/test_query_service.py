from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from lorcana.ratings.query_service import RatingPublicationNotFound, RatingQueryService

RUN_ID = UUID("00000000-0000-0000-0000-000000000201")
NOW = datetime(2026, 9, 13, 21, 0, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self):
        self.calls = []

    def resolve_publication(self, _connection, name):
        self.calls.append(("resolve", name))
        if name == "missing":
            return None
        return {
            "publication_name": name,
            "rating_run_id": RUN_ID,
            "published_at": NOW,
            "algorithm": "elo",
            "algorithm_version": "elo_v2_2player_only",
            "policy_version": "global_elo_v1",
            "input_count": 10,
            "player_count": 3,
            "ordered_input_digest": "abc",
        }

    def leaderboard(self, _connection, run_id, *, limit, offset):
        self.calls.append(("leaderboard", run_id, limit, offset))
        return [self._player(1, 11, 1600.0)]

    def player_rating(self, _connection, run_id, player_id):
        self.calls.append(("player", run_id, player_id))
        return None if player_id == 999 else self._player(2, player_id, 1550.0)

    @staticmethod
    def _player(rank, player_id, rating):
        return {
            "rank": rank,
            "player_id": player_id,
            "display_name": f"Player {player_id}",
            "username": f"user{player_id}",
            "rating": rating,
            "matches_played": 10,
            "wins": 6,
            "losses": 3,
            "draws": 1,
            "peak_rating": rating + 10,
        }


@contextmanager
def connection():
    yield object()


def test_leaderboard_resolves_one_publication_then_uses_exact_run():
    repo = FakeRepository()
    result = RatingQueryService(repository=repo, connection_factory=connection).leaderboard(limit=10, offset=5)
    assert result.publication.rating_run_id == RUN_ID
    assert result.entries[0].player_id == 11
    assert repo.calls == [
        ("resolve", "global_elo"),
        ("leaderboard", RUN_ID, 10, 5),
    ]


def test_player_query_uses_resolved_run_and_can_return_unrated_player():
    repo = FakeRepository()
    service = RatingQueryService(repository=repo, connection_factory=connection)
    assert service.player_by_id(7).player.player_id == 7
    assert service.player_by_id(999).player is None


def test_missing_publication_is_explicit():
    with pytest.raises(RatingPublicationNotFound):
        RatingQueryService(repository=FakeRepository(), connection_factory=connection).leaderboard(
            publication_name="missing"
        )


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (501, 0), (10, -1)])
def test_pagination_is_bounded(limit, offset):
    with pytest.raises(ValueError):
        RatingQueryService(repository=FakeRepository(), connection_factory=connection).leaderboard(
            limit=limit, offset=offset
        )

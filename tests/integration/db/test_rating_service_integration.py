from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, select, text

from lorcana.db.schema.playhub import (
    playhub_event_sync_state,
    playhub_events,
    playhub_matches,
    playhub_players,
    playhub_rounds,
)
from lorcana.db.schema.ratings import rating_publications, rating_run_inputs, rating_runs
from lorcana.ratings.policy import GlobalEloV1Policy
from lorcana.ratings.query_service import RatingQueryService
from lorcana.ratings.service import RatingService

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)


def _clear(db_engine) -> None:
    with db_engine.begin() as connection:
        connection.execute(text(
            "TRUNCATE TABLE "
            "rating_publications, rating_current, rating_history, rating_run_inputs, rating_runs, "
            "playhub_import_attempts, playhub_event_sync_state, playhub_discovery_runs, "
            "playhub_matches, playhub_registrations, playhub_rounds, playhub_phases, "
            "playhub_events, playhub_players, playhub_stores CASCADE"
        ))


def _seed(db_engine) -> None:
    with db_engine.begin() as connection:
        connection.execute(insert(playhub_players), [
            {"player_id": 1, "display_name": "Alice", "username": "alice"},
            {"player_id": 2, "display_name": "Bob", "username": "bob"},
            {"player_id": 3, "display_name": "Cara", "username": "cara"},
        ])
        connection.execute(insert(playhub_events), [
            {"event_id": 10, "name": "Complete Event", "start_datetime": NOW, "format": "Core Constructed"},
            {"event_id": 20, "name": "Partial Event", "start_datetime": NOW, "format": "Core Constructed"},
        ])
        connection.execute(insert(playhub_rounds), [
            {"round_id": 101, "event_id": 10, "round_number": 1},
            {"round_id": 102, "event_id": 10, "round_number": 2},
            {"round_id": 201, "event_id": 20, "round_number": 1},
        ])
        connection.execute(insert(playhub_matches), [
            {"match_id": 1, "event_id": 10, "round_id": 101, "player1_id": 1, "player2_id": 2,
             "participant_count": 2, "winner_id": 1, "status": "COMPLETE", "is_draw": False},
            {"match_id": 2, "event_id": 10, "round_id": 102, "player1_id": 2, "player2_id": 3,
             "participant_count": 2, "winner_id": 3, "status": "COMPLETE", "is_draw": False},
            {"match_id": 3, "event_id": 20, "round_id": 201, "player1_id": 1, "player2_id": 3,
             "participant_count": 2, "winner_id": 1, "status": "COMPLETE", "is_draw": False},
        ])
        connection.execute(insert(playhub_event_sync_state), [
            {"event_id": 10, "state": "complete"},
            {"event_id": 20, "state": "partial"},
        ])


def test_build_validate_publish_and_query_one_immutable_run(db_engine):
    _clear(db_engine)
    _seed(db_engine)
    try:
        service = RatingService.from_engine(db_engine, policy=GlobalEloV1Policy(), clock=lambda: NOW)
        result = service.build_and_publish(published_by="integration-test")
        assert result.input_count == 2
        assert result.player_count == 3
        assert result.exclusion_counts == {"event_not_complete": 1}

        with db_engine.connect() as connection:
            inputs = connection.execute(
                select(rating_run_inputs)
                .where(rating_run_inputs.c.rating_run_id == result.rating_run_id)
                .order_by(rating_run_inputs.c.sequence_number)
            ).mappings().all()
            assert [row["match_id"] for row in inputs] == [1, 2]
            assert inputs[0]["player1_id"] == 1
            assert inputs[0]["winner_id"] == 1
            assert connection.execute(
                select(rating_runs.c.status).where(rating_runs.c.rating_run_id == result.rating_run_id)
            ).scalar_one() == "published"

        query = RatingQueryService.from_engine(db_engine)
        leaderboard = query.leaderboard(limit=3)
        assert leaderboard.publication.rating_run_id == result.rating_run_id
        assert len(leaderboard.entries) == 3
        assert leaderboard.entries[0].display_name == "Alice"
        assert query.player_by_id(1).player is not None
    finally:
        _clear(db_engine)


def test_publication_retention_keeps_only_current_and_previous_runs(db_engine):
    _clear(db_engine)
    _seed(db_engine)
    try:
        service = RatingService.from_engine(db_engine, policy=GlobalEloV1Policy(), clock=lambda: NOW)
        first = service.build_and_publish(published_by="integration-test")
        second = service.build_and_publish(published_by="integration-test")
        third = service.build_and_publish(published_by="integration-test")

        with db_engine.connect() as connection:
            publication = connection.execute(
                select(
                    rating_publications.c.rating_run_id,
                    rating_publications.c.previous_rating_run_id,
                ).where(rating_publications.c.publication_name == "global_elo")
            ).one()
            assert publication.rating_run_id == third.rating_run_id
            assert publication.previous_rating_run_id == second.rating_run_id
            retained = set(connection.execute(select(rating_runs.c.rating_run_id)).scalars())
            assert retained == {second.rating_run_id, third.rating_run_id}
            assert first.rating_run_id not in retained
    finally:
        _clear(db_engine)

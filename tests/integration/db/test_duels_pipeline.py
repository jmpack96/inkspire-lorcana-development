from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from lorcana.db.schema.duels import duels_feature_sets, duels_normalizations, duels_replays
from lorcana.db.schema.identity import members
from lorcana.duels.service import DuelsService, DuelsServiceError
from lorcana.duels.types import HistoryPage

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "duels" / "01a0274d-2d09-74c5-9971-d820bb6c8941.replay.gz"
GAME_ID = "01a0274d-2d09-74c5-9971-d820bb6c8941"


class Resolver:
    def resolve(self, credential_ref: str) -> str:
        assert credential_ref == "env:DUELS_TEST_TOKEN"
        return "secret"


class FakeClient:
    def __init__(self, token: str, *, history, replay_source):
        assert token == "secret"
        self.history = history
        self.replay_source = replay_source

    def fetch_history_page(self, cursor=None):
        assert cursor is None
        return self.history

    def download_replay(self, replay_url: str) -> bytes:
        return self.replay_source["bytes"]

    def close(self):
        pass


def _clear(engine):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE duels_feature_sets, duels_normalizations, duels_replays, duels_game_observations, duels_games, duels_connections, members CASCADE"))


def test_duels_sync_replay_idempotency_revisioning_and_access(db_engine):
    _clear(db_engine)
    member_id = uuid4()
    other_member_id = uuid4()
    now = {"value": datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)}

    def clock():
        value = now["value"]
        now["value"] = value + timedelta(seconds=1)
        return value

    replay_source = {"bytes": FIXTURE.read_bytes()}
    history = HistoryPage(
        games=(
            {
                "game_id": GAME_ID,
                "match_format": "bo1",
                "mode": "matchmaking",
                "queue_id": "core-bo1",
                "queue_name": "Core Set 13 BO1",
                "ranked": True,
                "started_at": "2026-09-13T19:00:00Z",
                "result": "win",
                "went_first": True,
                "your_deck_colors": ["amber", "amethyst"],
                "opp_display_name": "Opponent",
                "opp_deck_colors": ["emerald", "steel"],
                "replay_id": "provider-replay-1",
                "replay_url": "https://storage.example/replay.gz",
            },
        ),
        next_cursor=None,
    )
    factory = lambda token: FakeClient(token, history=history, replay_source=replay_source)

    try:
        with db_engine.begin() as connection:
            connection.execute(
                members.insert(),
                [
                    dict(member_id=member_id, preferred_display_name="A", status="active", created_at=clock(), updated_at=clock()),
                    dict(member_id=other_member_id, preferred_display_name="B", status="active", created_at=clock(), updated_at=clock()),
                ],
            )

        service = DuelsService.from_engine(
            db_engine,
            credential_resolver=Resolver(),
            client_factory=factory,
            clock=clock,
        )
        connection_id = service.create_connection(member_id, credential_ref="env:DUELS_TEST_TOKEN")
        other_connection_id = service.create_connection(other_member_id, credential_ref="env:DUELS_TEST_TOKEN")

        sync = service.sync_history(connection_id)
        assert sync.games_observed == 1
        assert sync.new_games == 1
        assert sync.replay_candidates == 1
        assert sync.history_exhausted is True

        first = service.process_replay(connection_id, GAME_ID)
        assert first.replay_created is True
        assert first.normalization_created is True
        assert first.feature_set_created is True

        duplicate = service.process_replay(connection_id, GAME_ID)
        assert duplicate.replay_id == first.replay_id
        assert duplicate.replay_created is False
        assert duplicate.normalization_created is False
        assert duplicate.feature_set_created is False

        raw = json.loads(gzip.decompress(FIXTURE.read_bytes()))
        raw["testRevision"] = 2
        replay_source["bytes"] = gzip.compress(
            json.dumps(raw, separators=(",", ":")).encode("utf-8"),
            mtime=0,
        )
        revision = service.process_replay(connection_id, GAME_ID, force_refresh=True)
        assert revision.replay_created is True
        assert revision.replay_id != first.replay_id

        with pytest.raises(DuelsServiceError, match="not visible"):
            service.process_replay(other_connection_id, GAME_ID)

        replay_source["bytes"] = b"not-json"
        with pytest.raises(DuelsServiceError, match="valid UTF-8 JSON"):
            service.process_replay(connection_id, GAME_ID, force_refresh=True)

        with db_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(duels_replays)) == 3
            assert connection.scalar(select(func.count()).select_from(duels_normalizations)) == 2
            assert connection.scalar(select(func.count()).select_from(duels_feature_sets)) == 2
    finally:
        _clear(db_engine)

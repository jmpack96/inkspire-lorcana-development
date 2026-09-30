"""PostgreSQL coverage for ownership, history-only games and replay revisions."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from lorcana.db.schema.duels import duels_connections, duels_games, duels_game_observations, duels_replays, duels_normalizations
from lorcana.db.schema.identity import members
from lorcana.duels.practice_service import PracticeService
from lorcana.duels.practice_repository import PracticeRepository
from lorcana.duels.replay_parser import PARSER_VERSION

pytestmark = pytest.mark.integration


def test_practice_is_private_deduplicated_and_keeps_history_only_games(db_engine):
    now = datetime.now(timezone.utc)
    owner, other = uuid4(), uuid4()
    account, duplicate, foreign = uuid4(), uuid4(), uuid4()
    game, missing, secret = (str(uuid4()) for _ in range(3))
    replay_id, older_replay, foreign_replay = uuid4(), uuid4(), uuid4()
    norm, old_norm, foreign_norm = uuid4(), uuid4(), uuid4()
    with db_engine.begin() as c:
        c.execute(text("TRUNCATE TABLE duels_connections, members CASCADE"))
        c.execute(members.insert(), [dict(member_id=m, preferred_display_name="Test", status="active", created_at=now, updated_at=now) for m in (owner, other)])
        c.execute(duels_connections.insert(), [dict(connection_id=a, member_id=m, credential_ref="env:UNUSED", status="active", history_exhausted=True, created_at=now, updated_at=now) for a, m in ((account, owner), (duplicate, owner), (foreign, other))])
        c.execute(duels_games.insert(), [dict(game_id=g, started_at=now, first_seen_at=now, last_seen_at=now, ranked=True) for g in (game, missing, secret)])
        c.execute(duels_game_observations.insert(), [dict(connection_id=a, game_id=g, result="win", provider_payload={}, first_seen_at=now, last_seen_at=now) for a, g in ((account, game), (duplicate, missing), (account, missing), (foreign, secret))])
        from datetime import timedelta
        c.execute(duels_replays.insert(), [dict(replay_id=r, connection_id=a, game_id=g, fetched_at=now - timedelta(days=age), source_sha256=str(r), content_encoding="identity", compressed_bytes=b"{}", compressed_size=2, status="valid") for r, a, g, age in ((replay_id, account, game, 0), (older_replay, account, game, 1), (foreign_replay, foreign, secret, 0))])
        c.execute(duels_normalizations.insert(), [dict(normalization_id=n, replay_id=r, parser_version=PARSER_VERSION, schema_version=1, normalized={"decklist": [card] * 60}, normalized_sha256=str(n), warnings=[], status="valid", created_at=now) for n, r, card in ((norm, replay_id, "1-1"), (old_norm, older_replay, "2-2"), (foreign_norm, foreign_replay, "3-3"))])
    try:
        report = PracticeService.from_engine(db_engine).report(owner)
        assert {r["game_id"] for r in report["rows"]} == {game, missing}
        assert report["evidence_count"] == 1
        selected = next(r for r in report["rows"] if r["game_id"] == game)
        assert selected["normalization_id"] == norm
        assert next(r for r in report["rows"] if r["game_id"] == missing)["deck_id"] is None
        with db_engine.connect() as c:
            payloads = PracticeRepository().opening_evidence(c, member_id=owner, normalization_ids=[norm, foreign_norm])
            assert set(payloads) == {norm}
        assert PracticeService.from_engine(db_engine).report(uuid4())["rows"] == []
        from datetime import timedelta
        from lorcana.duels.matchups import MatchupRepository
        with db_engine.connect() as c:
            grouped = MatchupRepository().results(c, member_ids=[owner], since=now - timedelta(days=1), until=now)
            assert sum(r["games"] for r in grouped) == 2  # duplicate accounts do not double count
            assert all(r["team_observers"] == 1 for r in grouped)
        with db_engine.begin() as c:
            c.execute(duels_game_observations.insert().values(connection_id=foreign, game_id=game,
                result="loss", provider_payload={}, first_seen_at=now, last_seen_at=now))
        with db_engine.connect() as c:
            grouped = MatchupRepository().results(c, member_ids=[owner, other], since=now - timedelta(days=1), until=now)
            assert sum(r["games"] for r in grouped if r["team_observers"] == 2) == 2
            assert sum(r["games"] for r in grouped if r["team_observers"] == 1) == 2

    finally:
        with db_engine.begin() as c:
            c.execute(text("TRUNCATE TABLE duels_connections, members CASCADE"))
            c.execute(duels_games.delete().where(duels_games.c.game_id.in_([game, missing, secret])))

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lorcana.duels.practice import deck_fingerprint, opening_metrics, player_turns, record
from lorcana.duels.practice_service import PracticeService
from lorcana.interfaces.discord.application import DiscordApplication
from lorcana.interfaces.discord.practice_views import opening_views, summary_views

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "duels"


def replay(stem="01a09c43-d14f-79d0-baa0-f98904afbdae"):
    return json.loads(gzip.decompress((FIXTURES / f"{stem}.normalized.json.gz").read_bytes()))


def test_deck_identity_is_order_independent_and_quantity_sensitive():
    assert deck_fingerprint(["1-1", "1-2", "1-1"]) == deck_fingerprint(["1-2", "1-1", "1-1"])
    assert deck_fingerprint(["1-1", "1-2"]) != deck_fingerprint(["1-1", "1-2", "1-1"])
    assert deck_fingerprint(["1-1"]) != deck_fingerprint(["2-1"])
    for invalid in (None, [], {}, [None], [""], [{"id": "1-1"}]):
        assert deck_fingerprint(invalid) is None


def test_second_player_turns_exclude_opponent_responses_and_count_from_one():
    source = replay()
    before = deepcopy(source)
    turns = player_turns(source)
    assert turns[0][0]["gameplay_turn"] == 2
    assert turns[1][0]["gameplay_turn"] == 3
    assert all(a.get("active_player") == 1 for turn in turns for a in turn)
    assert 32 not in [a["seq"] for turn in turns for a in turn]  # opponent-turn choice
    metrics = opening_metrics(source, ("Grandmother Willow - Ancient Advisor",))
    assert metrics["mulligan_count"] == 2
    assert metrics["turns"][1]["target_played"] is True
    assert metrics["turns"][1]["ink"] == 2
    assert source == before


def test_first_player_undo_and_missing_evidence():
    source = replay("01a0274d-2d09-74c5-9971-d820bb6c8941")
    turns = player_turns(source)
    assert turns[0][0]["gameplay_turn"] == 1
    assert len(turns) == 7
    assert all(not a.get("undone") and a["type"] != "undo" for turn in turns for a in turn)
    source["parser_warnings"] = ["untrusted"]
    assert opening_metrics(source)["eligible"] is False
    source["parser_warnings"] = []
    source["effective_actions"] = source["effective_actions"][5:]
    assert opening_metrics(source)["eligible"] is False


def test_incomplete_turn_is_not_a_failed_target_or_ink_milestone():
    source = replay()
    second = player_turns(source)[1]
    seq = second[-1]["seq"]
    source["effective_actions"] = [a for a in source["effective_actions"] if a["seq"] < seq]
    metric = opening_metrics(source, ("Never Seen",))["turns"][1]
    assert metric["complete"] is False
    assert metric["ink"] is None
    assert metric["target_played"] is None


def test_invalid_mulligan_is_unknown_not_zero():
    source = replay()
    source["mulligan"]["drawn"] = []
    metrics = opening_metrics(source, ("11-13",))
    assert metrics["mulligan_count"] is None
    assert metrics["post_target"] is None
    assert metrics["post_uninkables"] is None


def test_target_play_is_not_claimed_as_ramp_resolution():
    source = replay()
    metrics = opening_metrics(source, ("Grandmother Willow – Ancient Advisor",))
    assert metrics["turns"][1]["target_played"] is True
    assert metrics["turns"][1]["ink"] == 2  # play and outcome remain separate


def test_draw_and_unknown_results_have_explicit_denominators():
    result = record([{"result": x} for x in ("win", "loss", "draw", None)])
    assert "33.3%" in result and "1 unknown" in result and "n=4" in result


@contextmanager
def reader():
    yield object()


class Repository:
    def __init__(self):
        self.rows = []
        self.payloads = {}
        self.calls = []

    def sync_status(self, connection, **kwargs):
        return {"connections": 1, "last_sync": None, "attention": 0}

    def history(self, connection, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.rows)

    def opening_evidence(self, connection, **kwargs):
        self.calls.append(kwargs)
        return {k: self.payloads[k] for k in kwargs["normalization_ids"] if k in self.payloads}


def row(**kwargs):
    return dict(game_id="game", connection_id=uuid4(), result="win", went_first=True,
                your_deck_colors=["ruby", "sapphire"], opponent_deck_colors=["emerald", "steel"],
                started_at=datetime.now(timezone.utc), ranked=True, queue_name="Infinity", mode="ranked",
                match_format="bo1", normalization_id=uuid4(), decklist=["1-1"] * 60, **kwargs)


def service(repo):
    return PracticeService(repository=repo, read_connection_factory=reader)


def test_service_bounds_openings_preserves_games_without_replays_and_scopes_member():
    repo = Repository()
    repo.rows = [row() for _ in range(105)]
    for i, r in enumerate(repo.rows):
        r["game_id"] = str(i)
        repo.payloads[r["normalization_id"]] = replay()
    repo.rows[-1]["normalization_id"] = None
    repo.rows[-1]["decklist"] = None
    member = uuid4()
    report = service(repo).report(member, openings=True)
    assert len(report["rows"]) == 105 and report["evidence_count"] == 104
    assert len(report["metrics"]) == 100 and report["openings_limited"]
    assert all(call["member_id"] == member for call in repo.calls)
    assert report["rows"][-1]["deck_id"] is None


def test_service_deck_filter_and_profile_do_not_require_ai():
    repo = Repository()
    repo.rows = [row(), row()]
    repo.rows[1]["decklist"] = ["2-2"] * 60
    chosen = deck_fingerprint(repo.rows[0]["decklist"])[:12]
    report = service(repo).report(uuid4(), openings=True, deck=chosen, profile="ruby_sapphire")
    assert len(report["rows"]) == 1
    assert report["targets"] == ("Tipo - Growing Son", "Sail the Azurite Sea")
    assert service(repo).report(uuid4(), cards="11-13,11-13")["targets"] == ("11-13",)


@pytest.mark.parametrize("kwargs", [{"days": 0}, {"days": 366}, {"days": True}, {"deck": "abc"},
                                      {"profile": "bad"}, {"cards": "  "}, {"ranked": "yes"}])
def test_service_rejects_invalid_filters(kwargs):
    with pytest.raises(ValueError):
        service(Repository()).report(uuid4(), **kwargs)


def test_private_application_uses_linked_member_not_requested_player():
    repo = Repository()
    member = uuid4()
    identity = SimpleNamespace(member_for_discord_user=lambda uid: SimpleNamespace(member_id=member) if uid == 123 else None)
    app = DiscordApplication(ratings=None, playhub=None, teams=None, identity=identity, practice=service(repo))
    assert app.coach is None
    response = app.practice_report(123)
    assert response.ephemeral and response.embeds
    assert repo.calls[-1]["member_id"] == member
    before = len(repo.calls)
    assert app.practice_report(999).ephemeral
    assert len(repo.calls) == before
    assert app.practice_report(123, days=0).ephemeral


def test_discord_pages_fit_limits_and_report_coverage():
    repo = Repository()
    repo.rows = [row() for _ in range(110)]
    for i, r in enumerate(repo.rows):
        r["game_id"] = f"019e11b9-c805-7f74-aea3-{i:012d}"
        r["decklist"] = [f"{i}-1"] * 60
        r["queue_name"] = "@everyone `" * 100
        repo.payloads[r["normalization_id"]] = replay()
    report = service(repo).report(uuid4(), openings=True, cards="Hamm - Piggy Bank")
    pages = summary_views(report) + opening_views(report)
    for page in pages:
        assert len(page.fields) <= 25
        assert len(page.description or "") <= 4096
        assert sum(len(f.name) + len(f.value) for f in page.fields) + len(page.title) + len(page.description or "") + len(page.footer or "") < 6000
        assert all(len(f.value) <= 1024 and len(f.name) <= 256 for f in page.fields)
    assert "newest 100" in opening_views(report)[0].description


def test_unknown_play_identity_and_multiplayer_are_not_false_certainty():
    source = replay()
    for action in source["effective_actions"]:
        if action.get("type") == "play":
            action["card_id"] = action["card_name"] = None
    assert opening_metrics(source, ("Unseen target",))["turns"][1]["target_played"] is None
    source["game"]["player_names"]["3"] = "Third player"
    assert opening_metrics(source)["eligible"] is False


def test_gateway_registers_practice_with_analyzer_disabled():
    pytest.importorskip("discord")
    import asyncio
    from sqlalchemy import create_engine
    from lorcana.bootstrap import ApplicationResources
    from lorcana.config import Settings
    from lorcana.interfaces.discord.bot import create_bot
    # Engine creation is lazy; no network, token, or database is used.
    resources = ApplicationResources(Settings(), create_engine("postgresql+psycopg://unused:unused@localhost/unused"))
    bot = create_bot(resources)
    try:
        assert bot.tree.get_command("practice") is None
        assert bot.tree.get_command("duels-summary") is not None
        assert [p.name for p in bot.tree.get_command("player-matchups").parameters] == ["player", "opponent_colors"]
        assert [p.name for p in bot.tree.get_command("team-matchups").parameters] == ["opponent_colors"]
    finally:
        asyncio.run(bot.close())


def test_play_from_another_zone_does_not_prove_card_was_in_hand():
    source = replay()
    for action in source["effective_actions"]:
        if action.get("type") == "play":
            action["card_id"] = "99-1"
            action["card_name"] = "Target from discard"
    metric = opening_metrics(source, ("Target from discard",))["turns"][1]
    assert metric["target_played"] is True
    assert metric["target_seen"] is False

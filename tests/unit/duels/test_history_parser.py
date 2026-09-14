from datetime import timezone

import pytest

from lorcana.duels.history_parser import DuelsHistoryParseError, parse_history_game, parse_history_page


def test_parse_history_page_and_game():
    payload = {
        "games": [
            {
                "game_id": "game-1",
                "match_id": None,
                "match_format": "bo1",
                "match_game_number": None,
                "mode": "matchmaking",
                "queue_id": "core-bo1",
                "queue_name": "Core Set 13 BO1",
                "ranked": True,
                "season_id": None,
                "season_name": "Core BO1 - Set 13",
                "started_at": "2026-09-13T20:15:00Z",
                "result": "win",
                "went_first": False,
                "your_deck_colors": ["Ruby", "Sapphire"],
                "opp_display_name": "Opponent",
                "opp_deck_colors": ["Steel", "Emerald"],
                "replay_id": "replay-1",
                "replay_url": "https://duels.ink/replay/replay-1.gz",
            }
        ],
        "next_cursor": "cursor-2",
    }
    page = parse_history_page(payload)
    assert page.next_cursor == "cursor-2"
    game = parse_history_game(page.games[0])
    assert game.game_id == "game-1"
    assert game.started_at.tzinfo == timezone.utc
    assert game.your_deck_colors == ["ruby", "sapphire"]
    assert game.provider_payload["queue_name"] == "Core Set 13 BO1"


def test_history_requires_timezone_aware_timestamp():
    with pytest.raises(DuelsHistoryParseError, match="timezone"):
        parse_history_game({"game_id": "g", "started_at": "2026-09-13T20:15:00"})


def test_history_page_rejects_non_object_games():
    with pytest.raises(DuelsHistoryParseError, match="games list"):
        parse_history_page({"games": ["bad"], "next_cursor": None})

from __future__ import annotations

import gzip
import json
from pathlib import Path

from lorcana.coach.evidence import compact_effective_actions

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "duels"


def test_compaction_preserves_citable_actions_and_removes_redundant_parser_baggage():
    path = FIXTURES / "01a0274d-2d09-74c5-9971-d820bb6c8941.normalized.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        normalized = json.load(handle)
    original = normalized["effective_actions"]
    compact = compact_effective_actions(original)

    assert [row["seq"] for row in compact] == [row["seq"] for row in original]
    assert all("raw_taken_action" not in row for row in compact)
    assert all("coach_context" not in row for row in compact)
    assert all("card_instance_id" not in row for row in compact)
    perspective_actions = [row for row in compact if row.get("actor_is_perspective")]
    assert any("context" in row for row in perspective_actions)

    original_bytes = len(json.dumps(original, separators=(",", ":")).encode())
    compact_bytes = len(json.dumps(compact, separators=(",", ":")).encode())
    # Retain combat stats and instance identity even when they increase input size.
    assert compact_bytes < original_bytes * 0.70


def test_compaction_never_invents_opponent_hidden_hand():
    action = {
        "seq": 1,
        "type": "play",
        "actor_is_perspective": True,
        "coach_context": {
            "my": {"hand_count": 1, "hand": [{"id": "1-1", "name": "Mine"}]},
            "opponent": {"hand_count": 2, "hand": [{"id": "9-9", "name": "Should not leak"}]},
        },
    }
    compact = compact_effective_actions([action])[0]
    assert compact["context"]["my"]["hand"][0]["id"] == "1-1"
    assert "hand" not in compact["context"]["opponent"]
    assert compact["context"]["opponent"]["hand_count"] == 2


def test_compaction_preserves_board_stats_for_rules_reasoning():
    card = {"id": "3-16", "instance_id": "instance-1", "strength": 2, "willpower": 2, "lore": 1}
    result = compact_effective_actions([{"seq": 1, "actor_is_perspective": True,
        "coach_context": {"my": {"field": [card]}}}])
    assert result[0]["context"]["my"]["field"][0] == card

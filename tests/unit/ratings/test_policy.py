from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from lorcana.ratings.policy import GlobalEloV1Policy, LegacyParityPolicy
from lorcana.ratings.types import RatingCandidate


def candidate(**changes) -> RatingCandidate:
    base = RatingCandidate(
        match_id=1,
        event_id=10,
        round_id=100,
        player1_id=1,
        player2_id=2,
        winner_id=1,
        is_draw=False,
        match_status="COMPLETE",
        is_bye=False,
        is_ghost_match=False,
        participant_count=2,
        event_start_datetime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        event_format="Core Constructed",
        event_sync_state="complete",
        phase_order=0,
        round_number=1,
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"match_status": "PENDING"}, "match_not_complete"),
        ({"is_bye": True}, "bye"),
        ({"is_ghost_match": True}, "ghost_match"),
        ({"participant_count": 3}, "not_two_player"),
        ({"player1_id": None}, "missing_player"),
        ({"player2_id": 1}, "same_player"),
        ({"winner_id": None}, "missing_result"),
        ({"winner_id": 9}, "invalid_winner"),
        ({"event_start_datetime": None}, "missing_event_start"),
    ],
)
def test_legacy_policy_rejects_invalid_source_facts(changes, reason):
    assert LegacyParityPolicy().evaluate(candidate(**changes)).reason == reason


def test_legacy_policy_includes_partial_event_for_exact_historical_parity():
    decision = LegacyParityPolicy().evaluate(candidate(event_sync_state="partial"))
    assert decision.included


def test_global_v1_requires_supported_format_and_complete_event():
    policy = GlobalEloV1Policy()
    assert policy.evaluate(candidate()).included
    assert policy.evaluate(candidate(event_sync_state="partial")).reason == "event_not_complete"
    assert policy.evaluate(candidate(event_format="Draft")).reason == "unsupported_event_format"

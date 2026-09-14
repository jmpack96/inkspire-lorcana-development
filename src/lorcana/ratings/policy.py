"""Pure, versioned eligibility policy for rating source matches."""

from __future__ import annotations

from typing import Protocol

from lorcana.ratings.types import EligibilityDecision, RatingCandidate


class RatingPolicy(Protocol):
    version: str

    def evaluate(self, candidate: RatingCandidate) -> EligibilityDecision: ...


class LegacyParityPolicy:
    """Reproduces the historical Elo population while making invalid winners explicit."""

    version = "legacy_parity_v1"

    def evaluate(self, candidate: RatingCandidate) -> EligibilityDecision:
        if candidate.match_status != "COMPLETE":
            return EligibilityDecision(False, "match_not_complete")
        if candidate.is_bye:
            return EligibilityDecision(False, "bye")
        if candidate.is_ghost_match:
            return EligibilityDecision(False, "ghost_match")
        if candidate.participant_count != 2:
            return EligibilityDecision(False, "not_two_player")
        if candidate.player1_id is None or candidate.player2_id is None:
            return EligibilityDecision(False, "missing_player")
        if candidate.player1_id == candidate.player2_id:
            return EligibilityDecision(False, "same_player")
        if candidate.winner_id is None and not candidate.is_draw:
            return EligibilityDecision(False, "missing_result")
        if candidate.winner_id is not None and candidate.winner_id not in {
            candidate.player1_id,
            candidate.player2_id,
        }:
            return EligibilityDecision(False, "invalid_winner")
        if candidate.event_start_datetime is None:
            return EligibilityDecision(False, "missing_event_start")
        return EligibilityDecision(True, "included")


class GlobalEloV1Policy:
    """Production policy: historical safety checks plus explicit format/state gates."""

    version = "global_elo_v1"
    accepted_formats = frozenset({"Core Constructed", "Infinity Constructed"})

    def __init__(self) -> None:
        self._base = LegacyParityPolicy()

    def evaluate(self, candidate: RatingCandidate) -> EligibilityDecision:
        base = self._base.evaluate(candidate)
        if not base.included:
            return base
        if candidate.event_format not in self.accepted_formats:
            return EligibilityDecision(False, "unsupported_event_format")
        if candidate.event_sync_state != "complete":
            return EligibilityDecision(False, "event_not_complete")
        return EligibilityDecision(True, "included")


def policy_from_name(name: str) -> RatingPolicy:
    normalized = name.strip().lower()
    if normalized in {"global", "global_elo_v1"}:
        return GlobalEloV1Policy()
    if normalized in {"legacy", "legacy_parity_v1"}:
        return LegacyParityPolicy()
    raise ValueError(f"Unknown rating policy: {name}")

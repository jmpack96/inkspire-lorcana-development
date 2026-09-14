"""Storage-independent records for rating policy, snapshots, and Elo calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple
from uuid import UUID


@dataclass(frozen=True)
class RatingCandidate:
    match_id: int
    event_id: int
    round_id: int
    player1_id: int | None
    player2_id: int | None
    winner_id: int | None
    is_draw: bool
    match_status: str | None
    is_bye: bool
    is_ghost_match: bool
    participant_count: int | None
    event_start_datetime: datetime | None
    event_format: str | None
    event_sync_state: str | None
    phase_order: int
    round_number: int


@dataclass(frozen=True)
class EligibilityDecision:
    included: bool
    reason: str


@dataclass(frozen=True)
class RatingMatch:
    match_id: int
    event_id: int
    round_id: int
    player1_id: int
    player2_id: int
    winner_id: int | None
    is_draw: bool
    start_datetime: datetime | str
    phase_order: int
    round_number: int


@dataclass(frozen=True)
class RatingRunInput:
    sequence_number: int
    match_id: int
    event_id: int
    event_start_datetime: datetime
    phase_order: int
    round_number: int
    player1_id: int
    player2_id: int
    winner_id: int | None
    is_draw: bool

    def as_rating_match(self, round_id: int = 0) -> RatingMatch:
        return RatingMatch(
            match_id=self.match_id,
            event_id=self.event_id,
            round_id=round_id,
            player1_id=self.player1_id,
            player2_id=self.player2_id,
            winner_id=self.winner_id,
            is_draw=self.is_draw,
            start_datetime=self.event_start_datetime,
            phase_order=self.phase_order,
            round_number=self.round_number,
        )


@dataclass(frozen=True)
class PlayerRating:
    rating: float = 1500.0
    matches: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    peak: float = 1500.0


class HistoryRow(NamedTuple):
    player_id: int
    match_id: int
    event_id: int
    rating_before: float
    rating_after: float
    rating_change: float
    opponent_id: int
    opponent_rating_before: float
    result: str


@dataclass(frozen=True)
class RatingBuildResult:
    rating_run_id: UUID
    input_count: int
    player_count: int
    ordered_input_digest: str
    exclusion_counts: dict[str, int]
    status: str
    publication_name: str | None = None

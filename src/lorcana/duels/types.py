"""Typed Duels application records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class DuelsConnection:
    connection_id: UUID
    member_id: UUID
    credential_ref: str
    status: str
    sync_cursor: str | None
    history_exhausted: bool


@dataclass(frozen=True)
class ParsedHistoryGame:
    game_id: str
    match_id: str | None
    match_format: str | None
    match_game_number: int | None
    mode: str | None
    queue_id: str | None
    queue_name: str | None
    ranked: bool | None
    season_id: str | None
    season_name: str | None
    started_at: datetime | None
    ended_at: datetime | None
    result: str | None
    went_first: bool | None
    your_deck_colors: list[str] | None
    opponent_display_name: str | None
    opponent_deck_colors: list[str] | None
    provider_replay_id: str | None
    replay_url: str | None
    provider_payload: dict[str, Any]


@dataclass(frozen=True)
class HistoryPage:
    games: tuple[dict[str, Any], ...]
    next_cursor: str | None


@dataclass(frozen=True)
class DuelsSyncResult:
    connection_id: UUID
    pages_fetched: int
    games_observed: int
    new_games: int
    replay_candidates: int
    replay_revisions_created: int
    normalizations_created: int
    feature_sets_created: int
    next_cursor: str | None
    history_exhausted: bool


@dataclass(frozen=True)
class ReplayProcessingResult:
    replay_id: UUID
    replay_created: bool
    normalization_id: UUID
    normalization_created: bool
    feature_set_id: UUID
    feature_set_created: bool

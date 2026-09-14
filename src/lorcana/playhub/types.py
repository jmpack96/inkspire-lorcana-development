"""Storage-independent records used by Play Hub parsing and services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class PlayHubStore:
    store_id: str
    name: str
    full_address: str | None = None
    city: str | None = None
    state_region: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    email: str | None = None
    website: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    last_synced: datetime | None = None


@dataclass(frozen=True)
class PlayHubEvent:
    event_id: int
    store_id: str | None
    name: str
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    timezone: str | None = None
    gameplay_format_id: str | None = None
    format: str | None = None
    event_format: str | None = None
    category: str | None = None
    display_status: str | None = None
    event_status: str | None = None
    lifecycle_status: str | None = None
    player_count: int | None = None
    registered_user_count: int | None = None
    capacity: int | None = None
    event_is_online: bool | None = None
    full_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    source_url: str | None = None
    discovered_at: datetime | None = None
    last_synced: datetime | None = None


@dataclass(frozen=True)
class PlayHubPhase:
    phase_id: int
    event_id: int
    phase_name: str | None = None
    phase_order: int | None = None
    round_type: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class PlayHubRound:
    round_id: int
    event_id: int
    phase_id: int | None = None
    round_number: int | None = None
    round_type: str | None = None
    status: str | None = None
    pairings_status: str | None = None
    standings_status: str | None = None
    final_round_in_event: bool = False
    # Context carried from the phase for diagnostics/presentation, not persisted.
    phase_name: str | None = None


@dataclass(frozen=True)
class PlayHubPlayer:
    player_id: int
    display_name: str | None = None
    username: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None


@dataclass(frozen=True)
class PlayHubRegistration:
    registration_id: int
    event_id: int
    player_id: int
    display_name_at_event: str | None = None
    registration_status: str | None = None
    matches_won: int | None = None
    matches_lost: int | None = None
    matches_drawn: int | None = None
    match_points: int | None = None
    placement: int | None = None
    registered_at: datetime | None = None
    last_synced: datetime | None = None


@dataclass(frozen=True)
class PlayHubMatch:
    match_id: int
    event_id: int
    round_id: int
    player1_id: int | None = None
    player2_id: int | None = None
    participant_count: int | None = None
    player1_score: int | None = None
    player2_score: int | None = None
    winner_id: int | None = None
    status: str | None = None
    table_number: int | None = None
    is_draw: bool = False
    is_intentional_draw: bool = False
    is_unintentional_draw: bool = False
    is_bye: bool = False
    is_loss: bool = False
    is_ghost_match: bool = False
    is_feature_match: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class EventBundle:
    store: PlayHubStore | None
    event: PlayHubEvent
    phases: tuple[PlayHubPhase, ...]
    rounds: tuple[PlayHubRound, ...]


@dataclass(frozen=True)
class StandingsBundle:
    players: tuple[PlayHubPlayer, ...]
    registrations: tuple[PlayHubRegistration, ...]


@dataclass(frozen=True)
class MatchBundle:
    players: tuple[PlayHubPlayer, ...]
    match: PlayHubMatch


@dataclass(frozen=True)
class PlayHubImportResult:
    event_id: int
    status: str
    rounds_expected: int
    rounds_imported: int
    registrations_found: int
    matches_found: int
    players_found: int
    import_attempt_id: UUID
    failed_round_ids: tuple[int, ...] = ()

@dataclass(frozen=True)
class DiscoverySelection:
    events: tuple[dict, ...]
    events_received: int
    duplicate_rows: int
    boundary_excluded: int
    missing_datetime: int
    missing_id: int


@dataclass(frozen=True)
class PlayHubDiscoveryResult:
    discovery_run_id: UUID | None
    start_datetime: datetime
    end_datetime: datetime
    events_received: int
    unique_events: int
    duplicate_rows: int
    persisted_events: int
    skipped: bool = False

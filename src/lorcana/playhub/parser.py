"""Pure Play Hub parsing and normalization.

No network, environment, or database imports belong here.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from lorcana.errors import LorcanaError
from lorcana.playhub.types import (
    EventBundle,
    MatchBundle,
    PlayHubEvent,
    PlayHubMatch,
    PlayHubPhase,
    PlayHubPlayer,
    PlayHubRegistration,
    PlayHubRound,
    PlayHubStore,
    StandingsBundle,
)

PLAYHUB_WEB_BASE = "https://tcg.ravensburgerplay.com"


class PlayHubParseError(LorcanaError):
    """A Play Hub payload is structurally invalid or cannot be normalized safely."""


def extract_event_data(html: str, event_id: int) -> dict[str, Any]:
    """Decode Next.js Flight hydration exactly once at each JSON layer.

    The regression this protects against involved escaped newlines/backslashes inside an
    embedded event object.  Do not replace escape sequences manually.
    """
    decoder = json.JSONDecoder()
    chunks: list[str] = []
    for match in re.finditer(r"self\.__next_f\.push\(\s*", html):
        try:
            payload, _ = decoder.raw_decode(html, match.end())
        except json.JSONDecodeError as error:
            raise PlayHubParseError(f"Invalid Next.js hydration JSON for event {event_id}") from error
        if (
            isinstance(payload, list)
            and len(payload) >= 2
            and payload[0] == 1
            and isinstance(payload[1], str)
        ):
            chunks.append(payload[1])

    search_text = "".join(chunks) if chunks else html
    pattern = rf'\{{\s*"id"\s*:\s*{re.escape(str(event_id))}\s*,'
    match = re.search(pattern, search_text)
    if match is None:
        raise PlayHubParseError(f"Could not locate embedded event data for event {event_id}")

    try:
        data, _ = decoder.raw_decode(search_text, match.start())
    except json.JSONDecodeError as error:
        raise PlayHubParseError(f"Invalid embedded event JSON for event {event_id}: {error}") from error

    if not isinstance(data, dict) or data.get("id") != event_id:
        raise PlayHubParseError("Extracted JSON object was not the expected event")
    return data


def parse_source_datetime(value: Any, *, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PlayHubParseError(f"Invalid datetime for {field}: {value!r}") from error
    else:
        raise PlayHubParseError(f"Unexpected datetime type for {field}: {type(value).__name__}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PlayHubParseError(f"Naive datetime for {field}: {value!r}")
    return parsed.astimezone(timezone.utc)


def _required_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise PlayHubParseError(f"Invalid integer for {field}: {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise PlayHubParseError(f"Missing or invalid integer for {field}: {value!r}") from error


def _optional_int(value: Any, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    return _required_int(value, field=field)


def _player_id(value: Any) -> int | None:
    if isinstance(value, Mapping):
        value = value.get("id")
    return _optional_int(value, field="winning_player")


def parse_event_bundle(raw: Mapping[str, Any], event_id: int, *, observed_at: datetime) -> EventBundle:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    observed_at = observed_at.astimezone(timezone.utc)
    raw_id = _required_int(raw.get("id"), field="event.id")
    if raw_id != event_id:
        raise PlayHubParseError(f"Expected event {event_id}, got event {raw_id}")

    raw_store = raw.get("store") or {}
    store: PlayHubStore | None = None
    store_id: str | None = None
    if raw_store:
        source_store_id = raw_store.get("id")
        if source_store_id is not None:
            store_id = str(source_store_id)
            store = PlayHubStore(
                store_id=store_id,
                name=raw_store.get("name") or f"Store {store_id}",
                full_address=raw_store.get("full_address"),
                city=raw_store.get("city"),
                state_region=raw_store.get("state"),
                country=raw_store.get("country"),
                latitude=raw_store.get("latitude"),
                longitude=raw_store.get("longitude"),
                email=raw_store.get("email"),
                website=raw_store.get("website"),
                first_seen=observed_at,
                last_seen=observed_at,
                last_synced=observed_at,
            )

    gameplay_format = raw.get("gameplay_format") or {}
    settings = raw.get("settings") or {}
    online_value = raw.get("event_is_online") if "event_is_online" in raw else None
    event = PlayHubEvent(
        event_id=event_id,
        store_id=store_id,
        name=raw.get("name") or f"Event {event_id}",
        start_datetime=parse_source_datetime(raw.get("start_datetime"), field="event.start_datetime"),
        end_datetime=parse_source_datetime(raw.get("end_datetime"), field="event.end_datetime"),
        timezone=raw.get("timezone"),
        gameplay_format_id=(str(gameplay_format.get("id")) if gameplay_format.get("id") is not None else None),
        format=gameplay_format.get("name"),
        event_format=raw.get("event_format"),
        category=raw.get("event_type"),
        display_status=raw.get("display_status"),
        event_status=raw.get("event_status"),
        lifecycle_status=settings.get("event_lifecycle_status"),
        player_count=_optional_int(raw.get("starting_player_count"), field="event.starting_player_count"),
        registered_user_count=_optional_int(raw.get("registered_user_count"), field="event.registered_user_count"),
        capacity=_optional_int(raw.get("capacity"), field="event.capacity"),
        event_is_online=(bool(online_value) if online_value is not None else None),
        full_address=raw.get("full_address"),
        latitude=raw.get("latitude"),
        longitude=raw.get("longitude"),
        source_url=f"{PLAYHUB_WEB_BASE}/events/{event_id}",
        discovered_at=observed_at,
        last_synced=observed_at,
    )

    phases: list[PlayHubPhase] = []
    rounds: list[PlayHubRound] = []
    for raw_phase in raw.get("tournament_phases") or []:
        phase_id = _required_int(raw_phase.get("id"), field="phase.id")
        phase_name = raw_phase.get("phase_name")
        phase = PlayHubPhase(
            phase_id=phase_id,
            event_id=event_id,
            phase_name=phase_name,
            phase_order=_optional_int(raw_phase.get("order_in_phases"), field="phase.order_in_phases"),
            round_type=raw_phase.get("round_type"),
            status=raw_phase.get("status"),
        )
        phases.append(phase)
        for raw_round in raw_phase.get("rounds") or []:
            round_id = _required_int(raw_round.get("id"), field="round.id")
            rounds.append(
                PlayHubRound(
                    round_id=round_id,
                    event_id=event_id,
                    phase_id=phase_id,
                    round_number=_optional_int(raw_round.get("round_number"), field="round.round_number"),
                    round_type=raw_round.get("round_type"),
                    status=raw_round.get("status"),
                    pairings_status=raw_round.get("pairings_status"),
                    standings_status=raw_round.get("standings_status"),
                    final_round_in_event=bool(raw_round.get("final_round_in_event", False)),
                    phase_name=phase_name,
                )
            )
    return EventBundle(store=store, event=event, phases=tuple(phases), rounds=tuple(rounds))


def parse_standings(
    event_id: int,
    raw_standings: Sequence[Mapping[str, Any]],
    *,
    observed_at: datetime,
) -> StandingsBundle:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    observed_at = observed_at.astimezone(timezone.utc)
    players: dict[int, PlayHubPlayer] = {}
    registrations: list[PlayHubRegistration] = []

    for standing in raw_standings:
        raw_player = standing.get("player") or {}
        player_id = _optional_int(raw_player.get("id"), field="standing.player.id")
        if player_id is None:
            continue
        event_status = standing.get("user_event_status") or {}
        username = event_status.get("best_identifier")
        players[player_id] = PlayHubPlayer(
            player_id=player_id,
            display_name=raw_player.get("best_identifier"),
            username=username,
            first_seen=observed_at,
            last_seen=observed_at,
        )
        registration_id = _optional_int(event_status.get("id"), field="standing.user_event_status.id")
        if registration_id is None:
            continue
        registrations.append(
            PlayHubRegistration(
                registration_id=registration_id,
                event_id=event_id,
                player_id=player_id,
                display_name_at_event=username,
                registration_status=event_status.get("registration_status"),
                matches_won=_optional_int(event_status.get("matches_won"), field="standing.matches_won"),
                matches_lost=_optional_int(event_status.get("matches_lost"), field="standing.matches_lost"),
                matches_drawn=_optional_int(event_status.get("matches_drawn"), field="standing.matches_drawn"),
                match_points=_optional_int(event_status.get("total_match_points"), field="standing.total_match_points"),
                placement=_optional_int(standing.get("rank"), field="standing.rank"),
                registered_at=None,
                last_synced=observed_at,
            )
        )
    return StandingsBundle(players=tuple(players.values()), registrations=tuple(registrations))


def parse_match(
    event_id: int,
    round_id: int,
    raw: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> MatchBundle:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    observed_at = observed_at.astimezone(timezone.utc)
    match_id = _required_int(raw.get("id"), field="match.id")

    player_ids: list[int] = []
    players: dict[int, PlayHubPlayer] = {}
    for relationship in raw.get("player_match_relationships") or []:
        raw_player = relationship.get("player") or {}
        player_id = _optional_int(raw_player.get("id"), field="match.player.id")
        if player_id is None:
            continue
        if player_id not in player_ids:
            player_ids.append(player_id)
        event_status = relationship.get("user_event_status") or {}
        players[player_id] = PlayHubPlayer(
            player_id=player_id,
            display_name=raw_player.get("best_identifier"),
            username=event_status.get("best_identifier"),
            first_seen=observed_at,
            last_seen=observed_at,
        )

    participant_count = len(player_ids)
    player1_id = player_ids[0] if participant_count >= 1 else None
    player2_id = player_ids[1] if participant_count >= 2 else None
    winner_id = _player_id(raw.get("winning_player"))
    winner_games = _optional_int(raw.get("games_won_by_winner"), field="match.games_won_by_winner")
    loser_games = _optional_int(raw.get("games_won_by_loser"), field="match.games_won_by_loser")
    player1_score: int | None = None
    player2_score: int | None = None
    if winner_id is not None:
        if winner_id == player1_id:
            player1_score, player2_score = winner_games, loser_games
        elif winner_id == player2_id:
            player1_score, player2_score = loser_games, winner_games

    intentional_draw = bool(raw.get("match_is_intentional_draw"))
    unintentional_draw = bool(raw.get("match_is_unintentional_draw"))
    is_bye = bool(raw.get("match_is_bye"))
    status = raw.get("status")
    is_draw = intentional_draw or unintentional_draw or (winner_id is None and not is_bye and status == "COMPLETE")

    match = PlayHubMatch(
        match_id=match_id,
        event_id=event_id,
        round_id=round_id,
        player1_id=player1_id,
        player2_id=player2_id,
        participant_count=participant_count,
        player1_score=player1_score,
        player2_score=player2_score,
        winner_id=winner_id,
        status=status,
        table_number=_optional_int(raw.get("table_number"), field="match.table_number"),
        is_draw=is_draw,
        is_intentional_draw=intentional_draw,
        is_unintentional_draw=unintentional_draw,
        is_bye=is_bye,
        is_loss=bool(raw.get("match_is_loss")),
        is_ghost_match=bool(raw.get("is_ghost_match")),
        is_feature_match=bool(raw.get("is_feature_match")),
        created_at=parse_source_datetime(raw.get("created_at"), field="match.created_at"),
        updated_at=parse_source_datetime(raw.get("updated_at"), field="match.updated_at"),
    )
    return MatchBundle(players=tuple(players.values()), match=match)


def round_should_have_matches(round_record: PlayHubRound) -> bool:
    return round_record.round_type == "PLAY_VS_OPPONENT" and round_record.pairings_status == "GENERATED"


def latest_generated_standings_round(rounds: Sequence[PlayHubRound]) -> PlayHubRound | None:
    for round_record in reversed(rounds):
        if round_record.standings_status == "GENERATED":
            return round_record
    return None


def select_discovered_events(
    raw_events: Sequence[Mapping[str, Any]],
    *,
    start_datetime: datetime,
    end_datetime: datetime,
) -> "DiscoverySelection":
    """Validate a discovery window, exclude the API's inclusive end boundary, and dedupe IDs."""
    from lorcana.playhub.types import DiscoverySelection

    if start_datetime.tzinfo is None or start_datetime.utcoffset() is None:
        raise ValueError("start_datetime must be timezone-aware")
    if end_datetime.tzinfo is None or end_datetime.utcoffset() is None:
        raise ValueError("end_datetime must be timezone-aware")
    start = start_datetime.astimezone(timezone.utc)
    end = end_datetime.astimezone(timezone.utc)
    if end <= start:
        raise ValueError("end_datetime must be after start_datetime")

    selected: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    duplicates = 0
    boundary_excluded = 0
    missing_datetime = 0
    missing_id = 0

    for raw in raw_events:
        raw_id = raw.get("id")
        if raw_id is None:
            missing_id += 1
            continue
        event_id = _required_int(raw_id, field="discovery.event.id")
        event_start = parse_source_datetime(raw.get("start_datetime"), field=f"discovery.event[{event_id}].start_datetime")
        if event_start is None:
            missing_datetime += 1
            continue
        if event_start == end:
            boundary_excluded += 1
            continue
        if event_start < start or event_start > end:
            raise PlayHubParseError(
                f"Play Hub returned event {event_id} at {event_start.isoformat()} outside "
                f"requested window [{start.isoformat()}, {end.isoformat()})"
            )
        if event_id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(event_id)
        selected.append(dict(raw))

    return DiscoverySelection(
        events=tuple(selected),
        events_received=len(raw_events),
        duplicate_rows=duplicates,
        boundary_excluded=boundary_excluded,
        missing_datetime=missing_datetime,
        missing_id=missing_id,
    )

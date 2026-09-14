"""Pure parsing/validation for Duels match-history payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from lorcana.duels.types import HistoryPage, ParsedHistoryGame


class DuelsHistoryParseError(ValueError):
    pass


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise DuelsHistoryParseError(f"{field} must be an integer, not boolean")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise DuelsHistoryParseError(f"{field} must be an integer") from error


def _optional_bool(value: Any, *, field: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise DuelsHistoryParseError(f"{field} must be a boolean")


def _optional_datetime(value: Any, *, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        # Accept seconds and JavaScript-style milliseconds.
        seconds = float(value)
        if abs(seconds) > 100_000_000_000:
            seconds /= 1000.0
        result = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError as error:
            raise DuelsHistoryParseError(f"{field} is not an ISO datetime") from error
    else:
        raise DuelsHistoryParseError(f"{field} has unsupported datetime type")
    if result.tzinfo is None or result.utcoffset() is None:
        raise DuelsHistoryParseError(f"{field} must include a timezone")
    return result.astimezone(timezone.utc)


def _colors(value: Any, *, field: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DuelsHistoryParseError(f"{field} must be a list of strings")
    return [item.strip().lower() for item in value if item.strip()]


def parse_history_page(payload: Any) -> HistoryPage:
    if not isinstance(payload, dict):
        raise DuelsHistoryParseError("Duels history response must be an object")
    games = payload.get("games")
    if not isinstance(games, list) or not all(isinstance(row, dict) for row in games):
        raise DuelsHistoryParseError("Duels history response has an invalid games list")
    cursor = payload.get("next_cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise DuelsHistoryParseError("Duels next_cursor must be a string or null")
    return HistoryPage(games=tuple(dict(row) for row in games), next_cursor=cursor or None)


def parse_history_game(payload: dict[str, Any]) -> ParsedHistoryGame:
    if not isinstance(payload, dict):
        raise DuelsHistoryParseError("Duels history game must be an object")
    game_id = _optional_text(payload.get("game_id"))
    if game_id is None:
        raise DuelsHistoryParseError("Duels history game is missing game_id")
    return ParsedHistoryGame(
        game_id=game_id,
        match_id=_optional_text(payload.get("match_id")),
        match_format=_optional_text(payload.get("match_format")),
        match_game_number=_optional_int(payload.get("match_game_number"), field="match_game_number"),
        mode=_optional_text(payload.get("mode")),
        queue_id=_optional_text(payload.get("queue_id")),
        queue_name=_optional_text(payload.get("queue_name")),
        ranked=_optional_bool(payload.get("ranked"), field="ranked"),
        season_id=_optional_text(payload.get("season_id")),
        season_name=_optional_text(payload.get("season_name")),
        started_at=_optional_datetime(payload.get("started_at"), field="started_at"),
        ended_at=_optional_datetime(payload.get("ended_at"), field="ended_at"),
        result=_optional_text(payload.get("result")),
        went_first=_optional_bool(payload.get("went_first"), field="went_first"),
        your_deck_colors=_colors(payload.get("your_deck_colors"), field="your_deck_colors"),
        opponent_display_name=_optional_text(payload.get("opp_display_name")),
        opponent_deck_colors=_colors(payload.get("opp_deck_colors"), field="opp_deck_colors"),
        provider_replay_id=_optional_text(payload.get("replay_id")),
        replay_url=_optional_text(payload.get("replay_url")),
        provider_payload=dict(payload),
    )

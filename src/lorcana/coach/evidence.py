"""Deterministic compaction of normalized replay evidence for model analysis.

The normalized replay remains the audit source of truth. This module removes
parser-only/repeated fields before model calls so Coach does not pay to send
hundreds of kilobytes of redundant state.
"""

from __future__ import annotations

from typing import Any, Mapping

_BASE_ACTION_KEYS = (
    "seq",
    "type",
    "actor",
    "actor_name",
    "actor_is_perspective",
    "active_player",
    "active_player_name",
    "gameplay_turn",
    "duels_frame_turn_number",
    "card_id",
    "card_name",
    "card_type",
    "source",
    "ability_name",
    "lore_gained",
    "new_lore_total",
    "prompt",
    "choices",
    "target_card_id",
    "target_name",
    "challenge",
    "undo",
)

_IDENTITY_CARD_KEYS = ("id", "card_id", "name", "card_name")
_FIELD_CARD_KEYS = _IDENTITY_CARD_KEYS + ("type", "exerted", "damage", "just_played", "cards_under")
_INKWELL_CARD_KEYS = _IDENTITY_CARD_KEYS + ("exerted", "hidden")

_CONTEXT_SCALARS = ("lore", "hand_count", "deck_count", "ink_count", "ready_ink")


def _without_empty(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value is not None and value != [] and value != {} and value != ""
    }


def _compact_card(card: Any, keys: tuple[str, ...] = _IDENTITY_CARD_KEYS) -> Any:
    if not isinstance(card, Mapping):
        return card
    return _without_empty({key: card.get(key) for key in keys})


def _compact_log_data(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, Mapping):
        return None
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        elif isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
            result[key] = value
        # Nested provider bookkeeping (for example effectDescriptionKeys) is
        # intentionally omitted; the human-readable message and catalog facts
        # carry the coaching-relevant meaning.
    return _without_empty(result)


def _compact_log(log: Any) -> Any:
    if not isinstance(log, Mapping):
        return log
    data = _compact_log_data(log.get("data"))
    # Keep human-readable events and scalar combat/choice facts; discard
    # provider log UUIDs and deeply nested template bookkeeping.
    return _without_empty({
        "type": log.get("type"),
        "player": log.get("player"),
        "turn_number": log.get("turn_number"),
        "message": log.get("message"),
        "cards": [_compact_card(card) for card in (log.get("cards") or [])],
        "data": data,
    })


def _compact_side(side: Any, *, include_hand: bool) -> dict[str, Any] | None:
    if not isinstance(side, Mapping):
        return None
    result = {key: side.get(key) for key in _CONTEXT_SCALARS}
    if include_hand:
        result["hand"] = [_compact_card(card) for card in (side.get("hand") or [])]
    field = side.get("field") or []
    if field:
        result["field"] = [_compact_card(card, _FIELD_CARD_KEYS) for card in field]
    items = side.get("items") or []
    if items:
        result["items"] = [_compact_card(card, _FIELD_CARD_KEYS) for card in items]
    inkwell = side.get("inkwell") or []
    if inkwell:
        result["inkwell"] = [_compact_card(card, _INKWELL_CARD_KEYS) for card in inkwell]
    discard = side.get("discard") or []
    if discard:
        result["discard"] = [_compact_card(card) for card in discard]
    return _without_empty(result)


def compact_context(context: Any) -> dict[str, Any] | None:
    if not isinstance(context, Mapping):
        return None
    return _without_empty({
        "status": context.get("status"),
        "current_player": context.get("current_player"),
        "turn_number": context.get("turn_number"),
        "has_inked_this_turn": context.get("has_inked_this_turn"),
        # The perspective player's hand is known from their replay. Opponent
        # hidden hand contents are intentionally not represented by the parser.
        "my": _compact_side(context.get("my"), include_hand=True),
        "opponent": _compact_side(context.get("opponent"), include_hand=False),
    })


def compact_effective_action(action: Mapping[str, Any]) -> dict[str, Any]:
    compact = {key: action.get(key) for key in _BASE_ACTION_KEYS}
    logs = [_compact_log(log) for log in (action.get("logs") or [])]
    if logs:
        compact["logs"] = logs

    # Decision-state snapshots are most valuable for the player's own actions.
    # Keep them there and at game/setup boundaries, rather than duplicating a
    # large board snapshot after every opponent action.
    if action.get("actor_is_perspective") is True or action.get("type") in {
        "choose_starting_player",
        "mulligan",
        "game_finish",
    }:
        context = compact_context(action.get("coach_context"))
        if context:
            compact["context"] = context
    return _without_empty(compact)


def compact_effective_actions(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        raise ValueError("effective_actions must be a list")
    result: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, Mapping):
            raise ValueError("effective_actions entries must be objects")
        result.append(compact_effective_action(action))
    return result

"""Versioned deterministic features derived from normalized Duels replays."""

from __future__ import annotations

from collections import Counter
from typing import Any

FEATURE_EXTRACTOR_VERSION = "duels_features_v1"


def _card_ref(card: Any) -> dict[str, Any]:
    if not isinstance(card, dict):
        return {}
    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "instance_id": card.get("instance_id"),
        "cost": card.get("cost"),
        "inkable": card.get("inkable"),
    }


def _action_ref(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": action.get("seq"),
        "type": action.get("type"),
        "turn": action.get("gameplay_turn"),
        "actor": action.get("actor"),
        "actor_is_perspective": action.get("actor_is_perspective"),
        "card_id": action.get("card_id"),
        "card_name": action.get("card_name"),
        "card_instance_id": action.get("card_instance_id"),
        "source": action.get("source"),
        "ability_name": action.get("ability_name"),
        "lore_gained": action.get("lore_gained"),
    }


def extract_features(normalized: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(normalized, dict):
        raise ValueError("normalized replay must be an object")
    game = normalized.get("game")
    actions = normalized.get("effective_actions")
    if not isinstance(game, dict) or not isinstance(actions, list):
        raise ValueError("normalized replay is missing game/effective_actions")
    if not all(isinstance(action, dict) for action in actions):
        raise ValueError("effective_actions must contain objects")

    perspective = game.get("perspective")
    first_player = game.get("first_player")
    winner = game.get("winner")
    perspective_actions = [a for a in actions if a.get("actor_is_perspective") is True]
    action_counts = Counter(str(a.get("type") or "unknown") for a in actions)
    perspective_counts = Counter(str(a.get("type") or "unknown") for a in perspective_actions)

    turn_starts: dict[str, Any] = {}
    turn_actions: dict[str, list[dict[str, Any]]] = {}
    for action in perspective_actions:
        turn = action.get("gameplay_turn")
        if not isinstance(turn, int):
            continue
        key = str(turn)
        turn_actions.setdefault(key, []).append(_action_ref(action))
        if key not in turn_starts:
            context = action.get("coach_context")
            if isinstance(context, dict):
                mine = context.get("my")
                if isinstance(mine, dict):
                    turn_starts[key] = {
                        "seq": action.get("seq"),
                        "hand": [_card_ref(card) for card in (mine.get("hand") or [])],
                        "hand_count": mine.get("hand_count"),
                        "ink_count": mine.get("ink_count"),
                        "ready_ink": mine.get("ready_ink"),
                        "lore": mine.get("lore"),
                    }

    mulligan = normalized.get("mulligan") or {}
    if not isinstance(mulligan, dict):
        mulligan = {}

    return {
        "schema_version": 1,
        "extractor_version": FEATURE_EXTRACTOR_VERSION,
        "game": {
            "game_id": game.get("game_id"),
            "perspective": perspective,
            "first_player": first_player,
            "perspective_went_first": (
                perspective == first_player if perspective is not None and first_player is not None else None
            ),
            "winner": winner,
            "perspective_won": (
                perspective == winner if perspective is not None and winner is not None else None
            ),
            "victory_reason": game.get("victory_reason"),
            "turn_count": game.get("turn_count"),
        },
        "mulligan": {
            "count": mulligan.get("count"),
            "kept": [_card_ref(card) for card in (mulligan.get("kept") or [])],
            "sent_back": [_card_ref(card) for card in (mulligan.get("sent_back") or [])],
            "drawn": [_card_ref(card) for card in (mulligan.get("drawn") or [])],
            "source": mulligan.get("source"),
        },
        "action_counts": dict(sorted(action_counts.items())),
        "perspective_action_counts": dict(sorted(perspective_counts.items())),
        "perspective_actions": [_action_ref(action) for action in perspective_actions],
        "perspective_turns": {
            key: {"start": turn_starts.get(key), "actions": value}
            for key, value in sorted(turn_actions.items(), key=lambda item: int(item[0]))
        },
        "undo_ranges": normalized.get("undo_ranges") or [],
        "parser_warning_count": len(normalized.get("parser_warnings") or []),
    }

"""Compact versioned read data; full replay evidence remains authoritative."""
from collections import Counter
from copy import deepcopy

PROJECTION_VERSION = 1


def validated_mulligan(evidence):
    """Missing, inconsistent, or warned opening evidence is not a zero."""
    if not isinstance(evidence, dict) or evidence.get("parser_warnings"):
        return None
    game = evidence.get("game") or {}
    if not isinstance(game, dict) or game.get("perspective") is None:
        return None
    names = game.get("player_names") or {}
    if names and len(names) != 2:
        return None
    initial = evidence.get("starting_hand")
    mulligan = evidence.get("mulligan")
    if not isinstance(mulligan, dict):
        return None
    kept, sent, drawn = (mulligan.get(k) for k in ("kept", "sent_back", "drawn"))
    count = mulligan.get("count")
    if not (type(count) is int and 0 <= count <= 7
            and all(isinstance(group, list) and
                    all(isinstance(card, dict) and isinstance(card.get("id"), str) and card["id"]
                        for card in group) for group in (initial, kept, sent, drawn))):
        return None
    if not (len(initial) == 7 and len(sent) == len(drawn) == count and len(kept) + count == 7
            and Counter(c["id"] for c in initial) == Counter(c["id"] for c in kept + sent)):
        return None
    return count



def _card(card):
    if not isinstance(card, dict):
        return deepcopy(card)
    return {k: deepcopy(card[k]) for k in ("id", "name", "inkable") if k in card}


def _cards(value):
    return [_card(c) for c in value] if isinstance(value, list) else deepcopy(value)


def compact_opening(normalized):
    evidence = {k: deepcopy(normalized.get(k)) for k in ("game", "parser_warnings")}
    evidence["starting_hand"] = _cards(normalized.get("starting_hand"))
    mulligan = normalized.get("mulligan")
    evidence["mulligan"] = ({k: _cards(v) if k in ("kept", "sent_back", "drawn") else deepcopy(v)
                             for k, v in mulligan.items()} if isinstance(mulligan, dict) else deepcopy(mulligan))
    actions = []
    for action in normalized.get("effective_actions") or []:
        item = {k: deepcopy(action[k]) for k in ("seq", "type", "active_player", "gameplay_turn",
                "actor_is_perspective", "undone", "card_id", "card_name") if k in action}
        context = action.get("coach_context") or {}
        mine = context.get("my") or {}
        item["coach_context"] = {k: deepcopy(context[k]) for k in ("status", "current_player") if k in context}
        item["coach_context"]["my"] = {k: deepcopy(mine[k]) for k in ("ink_count", "ready_ink") if k in mine}
        if "hand" in mine:
            item["coach_context"]["my"]["hand"] = _cards(mine["hand"])
        actions.append(item)
    evidence["effective_actions"] = actions
    return evidence


def projection_values(normalized):
    return {"version": PROJECTION_VERSION,
            "mulligan_count": validated_mulligan(normalized),
            "decklist": deepcopy(normalized.get("decklist")),
            "opening_evidence": compact_opening(normalized)}

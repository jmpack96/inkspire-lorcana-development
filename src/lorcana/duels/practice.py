"""Pure, observational practice metrics. No card rules engine or model calls."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any

PRACTICE_VERSION = "practice_v1"
RAMP_CARDS = ("Tipo - Growing Son", "Sail the Azurite Sea")


def deck_fingerprint(decklist: Any) -> str | None:
    """Exact provider card multiset, including printing IDs; never infer missing cards."""
    if not isinstance(decklist, list) or not decklist:
        return None
    if not all(isinstance(card, str) and card.strip() for card in decklist):
        return None
    counts = sorted(Counter(card.strip() for card in decklist).items())
    return hashlib.sha256(json.dumps(counts, separators=(",", ":")).encode()).hexdigest()


def card_key(value: str) -> str:
    return " ".join(re.sub(r"[–—−]", "-", value).casefold().split())


def target_present(cards: Any, targets: tuple[str, ...]) -> bool | None:
    if not isinstance(cards, list) or not all(isinstance(c, dict) for c in cards):
        return None
    keys = {card_key(t) for t in targets}
    if any(keys.intersection(card_key(str(c.get(k) or "")) for k in ("id", "name")) for c in cards):
        return True
    # Missing identities cannot establish absence.
    if any(not c.get("id") or not c.get("name") for c in cards):
        return None
    return False


def player_turns(normalized: dict) -> list[list[dict]] | None:
    """Count observed active-player segments, not Duels round labels.

    Require the game start so a partial replay cannot masquerade as turn one.
    Responses on the other player's turn are excluded. Undo control frames can
    establish a boundary but are never counted as decisions.
    """
    game = normalized.get("game") or {}
    perspective, first = game.get("perspective"), game.get("first_player")
    names = game.get("player_names") or {}
    if (perspective is None or first is None or normalized.get("parser_warnings")
            or (names and len(names) != 2)):
        return None
    actions = normalized.get("effective_actions") or []
    if not any(a.get("type") == "mulligan" and a.get("actor_is_perspective") is True for a in actions):
        return None
    turns: list[list[dict]] = []
    previous = None
    started = False
    for action in actions:
        if action.get("undone"):
            continue
        context = action.get("coach_context") or {}
        active = action.get("active_player")
        if active is None and context.get("status") == "playing":
            active = context.get("current_player")
        label = action.get("gameplay_turn")
        if active is None or not isinstance(label, int):
            continue
        if not started:
            if active != first or label != 1:
                return None
            started = True
        segment = (active, label)
        if segment != previous:
            if active == perspective:
                turns.append([])
            previous = segment
        if active == perspective and action.get("actor_is_perspective") is True and action.get("type") != "undo":
            turns[-1].append(action)
    return turns if started else None


def opening_metrics(normalized: dict, targets: tuple[str, ...] = ()) -> dict:
    turns = player_turns(normalized)
    output: dict = {"version": PRACTICE_VERSION, "eligible": turns is not None}
    if turns is None:
        return output
    initial = normalized.get("starting_hand")
    mulligan = normalized.get("mulligan") or {}
    kept, sent, drawn = (mulligan.get(k) for k in ("kept", "sent_back", "drawn"))
    count = mulligan.get("count")
    valid_mulligan = (
        isinstance(initial, list) and len(initial) == 7
        and all(isinstance(group, list) and all(isinstance(c, dict) and c.get("id") for c in group)
                for group in (initial, kept, sent, drawn))
        and type(count) is int and 0 <= count <= 7
        and len(sent) == len(drawn) == count and len(kept) + count == 7
        and Counter(c["id"] for c in initial) == Counter(c["id"] for c in kept + sent)
    )
    output["mulligan_count"] = count if valid_mulligan else None
    post = kept + drawn if valid_mulligan else None
    output["post_uninkables"] = (
        sum(c["inkable"] is False for c in post)
        if post is not None and all(type(c.get("inkable")) is bool for c in post) else None
    )
    if targets:
        output["initial_target"] = target_present(initial, targets) if valid_mulligan else None
        output["kept_target"] = target_present(kept, targets) if valid_mulligan else None
        output["post_target"] = target_present(post, targets)
    output["turns"] = []
    for number, actions in enumerate(turns[:3], 1):
        ends = [a for a in actions if a.get("type") == "end_turn"]
        end_context = (ends[-1].get("coach_context") or {}) if ends else {}
        mine = end_context.get("my") or {}
        metric = {"number": number, "complete": bool(ends), "ink": mine.get("ink_count"),
                  "ready_ink": mine.get("ready_ink"), "end_seq": ends[-1].get("seq") if ends else None}
        if targets:
            sightings = [target_present((a.get("coach_context") or {}).get("my", {}).get("hand"), targets)
                         for a in actions]
            plays = [target_present([{"id": a.get("card_id"), "name": a.get("card_name")}], targets)
                     for a in actions if a.get("type") == "play"]
            played = True if True in plays else (None if None in plays else False)
            metric["target_seen"] = True if True in sightings else (False if sightings and all(s is False for s in sightings) else None)
            metric["target_played"] = played if ends or played is True else None
        output["turns"].append(metric)
    return output


def record(rows: list[dict]) -> str:
    counts = Counter(str(r.get("result") or "").strip().lower() for r in rows)
    wins = counts["win"] + counts["won"]
    losses = counts["loss"] + counts["lost"]
    draws = counts["draw"] + counts["tie"]
    unknown = len(rows) - wins - losses - draws
    total = wins + losses + draws
    rate = f"{100 * wins / total:.1f}% wins" if total else "win rate n/a"
    return f"{wins}W–{losses}L–{draws}D | {rate} | n={len(rows)}" + (f" | {unknown} unknown" if unknown else "")


def colors_label(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "Unknown"
    return "/".join(sorted({str(c).strip().title() for c in value}))

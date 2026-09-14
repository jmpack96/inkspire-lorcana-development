#!/usr/bin/env python3
"""Normalize a Duels.ink duels-replay-v1 JSON replay.

No third-party dependencies are required.

Duels replay patches are JSON-Patch-like, but `replace` is used as a
"set" operation even when the target key does not already exist. This
parser therefore implements the three operations seen in Duels replays
(add/remove/replace) with Duels-compatible semantics instead of using a
strict RFC 6902 library.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_PROBE_DIR = Path("data/duels/raw")
DEFAULT_OUTPUT_DIR = Path("data/duels/normalized")

PARSER_VERSION = "duels_replay_parser_v1"
NORMALIZED_SCHEMA_VERSION = 3

NORMALIZED_TYPES = {
    "CHOOSE_STARTING_PLAYER": "choose_starting_player",
    "MULLIGAN": "mulligan",
    "ADD_TO_INK": "ink",
    "PLAY_CARD": "play",
    "QUEST": "quest",
    "ATTACK": "challenge",
    "ACTIVATE_ABILITY": "activate_ability",
    "BOOST": "boost",
    "RESPOND_TO_PROMPT": "choice",
    "END_TURN": "end_turn",
    "CONCEDE": "concede",
    "GAME_FINISH": "game_finish",
}


# ---------------------------------------------------------------------------
# Duels-compatible patch application
# ---------------------------------------------------------------------------

def _decode_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _pointer_tokens(path: str) -> List[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {path!r}")
    return [_decode_pointer_token(part) for part in path[1:].split("/")]


def _resolve_parent(document: Any, path: str, *, create_missing: bool) -> Tuple[Any, str]:
    tokens = _pointer_tokens(path)
    if not tokens:
        raise ValueError("Root path has no parent")

    current = document

    for token in tokens[:-1]:
        if isinstance(current, list):
            if token == "-":
                raise ValueError(f"'-' is not valid in an intermediate path: {path}")
            index = int(token)
            if index < 0 or index >= len(current):
                raise IndexError(f"List index {index} out of range while resolving {path}")
            current = current[index]

        elif isinstance(current, dict):
            if token not in current:
                if not create_missing:
                    raise KeyError(path)
                current[token] = {}
            current = current[token]

        else:
            raise TypeError(
                f"Cannot traverse through {type(current).__name__} while resolving {path}"
            )

    return current, tokens[-1]


def apply_duels_patch_operation(document: Any, operation: Dict[str, Any]) -> Any:
    """Apply one Duels patch operation in place and return the document.

    Semantics observed in duels-replay-v1:
      * add: standard add/insert behavior
      * remove: remove if present; missing remove is treated as a no-op
      * replace: behaves like SET, so a missing dictionary key is created

    We intentionally fail on impossible sparse list replacements because
    silently inventing list entries would corrupt reconstructed game state.
    """

    op = operation.get("op")
    path = operation.get("path")

    if op not in {"add", "remove", "replace"}:
        raise ValueError(f"Unsupported Duels patch operation: {op!r}")
    if not isinstance(path, str):
        raise ValueError(f"Patch operation is missing a string path: {operation!r}")

    # Root replacement is not present in the sample replay, but supporting it
    # costs little and keeps the implementation well-defined.
    if path == "":
        if op in {"add", "replace"}:
            return copy.deepcopy(operation.get("value"))
        return None

    parent, last = _resolve_parent(
        document,
        path,
        create_missing=(op in {"add", "replace"}),
    )

    if isinstance(parent, list):
        if last == "-":
            if op == "remove":
                return document
            if op == "replace":
                raise IndexError(f"Cannot replace '-' list position at {path}")
            parent.append(copy.deepcopy(operation.get("value")))
            return document

        index = int(last)

        if op == "add":
            if index < 0 or index > len(parent):
                raise IndexError(f"List add index {index} out of range at {path}")
            parent.insert(index, copy.deepcopy(operation.get("value")))

        elif op == "replace":
            if index < 0 or index > len(parent):
                raise IndexError(f"List replace index {index} out of range at {path}")
            if index == len(parent):
                # Duels occasionally uses replace as SET. Appending at exactly
                # len(list) is the natural list equivalent.
                parent.append(copy.deepcopy(operation.get("value")))
            else:
                parent[index] = copy.deepcopy(operation.get("value"))

        elif op == "remove":
            if 0 <= index < len(parent):
                parent.pop(index)

        return document

    if not isinstance(parent, dict):
        raise TypeError(f"Patch parent at {path} is {type(parent).__name__}, not dict/list")

    if op in {"add", "replace"}:
        # This is the key Duels compatibility behavior: replace means SET.
        parent[last] = copy.deepcopy(operation.get("value"))
    elif op == "remove":
        parent.pop(last, None)

    return document


def apply_duels_patch(document: Any, operations: Iterable[Dict[str, Any]]) -> Any:
    for operation in operations:
        document = apply_duels_patch_operation(document, operation)
    return document


# ---------------------------------------------------------------------------
# Replay helpers
# ---------------------------------------------------------------------------

def card_summary(card: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(card, dict):
        return None

    return {
        "id": card.get("id"),
        "instance_id": card.get("instanceId"),
        "name": card.get("fullName") or card.get("name"),
        "type": card.get("type"),
        "colors": card.get("colors") or [],
        "cost": card.get("cost"),
        "inkable": card.get("inkable"),
        "strength": card.get("strength"),
        "willpower": card.get("willpower"),
        "lore": card.get("lore"),
        "damage": card.get("damage"),
        "exerted": card.get("exerted"),
        "just_played": card.get("justPlayed"),
        "cards_under": len(card.get("cardsUnder") or []),
    }


def context_hand_card(card: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(card, dict):
        return None
    return {
        "id": card.get("id"),
        "instance_id": card.get("instanceId"),
        "name": card.get("fullName") or card.get("name"),
        "type": card.get("type"),
        "cost": card.get("cost"),
        "inkable": card.get("inkable"),
    }


def context_board_card(card: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(card, dict):
        return None
    return {
        "id": card.get("id"),
        "instance_id": card.get("instanceId"),
        "name": card.get("fullName") or card.get("name"),
        "type": card.get("type"),
        "strength": card.get("strength"),
        "willpower": card.get("willpower"),
        "lore": card.get("lore"),
        "damage": card.get("damage"),
        "exerted": card.get("exerted"),
        "just_played": card.get("justPlayed"),
        "cards_under": len(card.get("cardsUnder") or []),
    }


def player_name(names: Dict[str, Any], player: Any) -> Optional[str]:
    if player is None:
        return None
    return names.get(str(player)) or names.get(player) or f"Player {player}"


def summarize_inkwell(entries: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for entry in entries or []:
        if isinstance(entry, dict):
            card = card_summary(entry.get("card"))
            result.append(
                {
                    "hidden": entry.get("hidden"),
                    "exerted": entry.get("exerted")
                    if "exerted" in entry
                    else (entry.get("card") or {}).get("exerted")
                    if isinstance(entry.get("card"), dict)
                    else None,
                    "card": card,
                }
            )
    return result


def state_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """Compact coach-facing snapshot of the visible game state.

    The raw replay remains the authoritative archive. Normalized output keeps
    only the state needed to understand decisions so we do not multiply a
    ~300 KB replay into several megabytes of repeated card metadata.
    """

    mine = state.get("myPlayer") or {}
    opponent = state.get("opponent") or {}

    my_ink = summarize_inkwell(mine.get("inkwell"))
    opp_ink = summarize_inkwell(opponent.get("inkwell"))

    def small_ink(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for entry in entries:
            card = entry.get("card") or {}
            result.append(
                {
                    "hidden": entry.get("hidden"),
                    "exerted": entry.get("exerted"),
                    "card_id": card.get("id"),
                    "card_name": card.get("name"),
                }
            )
        return result

    return {
        "status": state.get("status"),
        "current_player": state.get("currentPlayer"),
        "turn_number": state.get("turnNumber"),
        "has_inked_this_turn": state.get("hasInkedThisTurn"),
        "my": {
            "lore": mine.get("lore"),
            "hand": [context_hand_card(c) for c in mine.get("hand") or []],
            "hand_count": len(mine.get("hand") or []),
            "deck_count": mine.get("deckCount"),
            "field": [context_board_card(c) for c in mine.get("field") or []],
            "items": [context_board_card(c) for c in mine.get("items") or []],
            "inkwell": small_ink(my_ink),
            "ink_count": len(my_ink),
            "ready_ink": sum(1 for x in my_ink if x.get("exerted") is False),
            "discard": [
                {"id": c.get("id"), "name": c.get("fullName") or c.get("name")}
                for c in mine.get("discard") or []
                if isinstance(c, dict)
            ],
        },
        "opponent": {
            "lore": opponent.get("lore"),
            "hand_count": opponent.get("handCount"),
            "deck_count": opponent.get("deckCount"),
            "field": [context_board_card(c) for c in opponent.get("field") or []],
            "items": [context_board_card(c) for c in opponent.get("items") or []],
            "inkwell": small_ink(opp_ink),
            "ink_count": len(opp_ink),
            "ready_ink": sum(1 for x in opp_ink if x.get("exerted") is False),
            "discard": [
                {"id": c.get("id"), "name": c.get("fullName") or c.get("name")}
                for c in opponent.get("discard") or []
                if isinstance(c, dict)
            ],
        },
    }

def compact_logs(logs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for log in logs:
        result.append(
            {
                "id": log.get("id"),
                "type": log.get("type"),
                "player": log.get("player"),
                "turn_number": log.get("turnNumber"),
                "message": log.get("message"),
                "cards": [
                    {"id": ref.get("id"), "name": ref.get("name")}
                    for ref in (log.get("cardRefs") or [])
                ],
                "data": copy.deepcopy(log.get("data")) if log.get("data") else None,
            }
        )
    return result


def first_log(logs: Iterable[Dict[str, Any]], log_type: str) -> Optional[Dict[str, Any]]:
    return next((log for log in logs if log.get("type") == log_type), None)


def infer_play_from_logs(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    log = first_log(logs, "CARD_PLAYED")
    if not log:
        return {}

    refs = log.get("cardRefs") or []
    if not refs:
        return {}

    message = log.get("message") or ""
    result: Dict[str, Any] = {
        "card_id": refs[0].get("id"),
        "card_name": refs[0].get("name"),
        "play_method": "sing" if " sang " in f" {message.lower()} " else "play",
        "derived_from_logs": True,
    }

    if result["play_method"] == "sing" and len(refs) > 1:
        result["singer"] = {"id": refs[1].get("id"), "name": refs[1].get("name")}

    return result


def infer_boost_from_logs(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    log = first_log(logs, "CARD_BOOSTED")
    if not log:
        return {}
    refs = log.get("cardRefs") or []
    if not refs:
        return {}
    return {
        "card_id": refs[0].get("id"),
        "card_name": refs[0].get("name"),
        "derived_from_logs": True,
    }


def infer_ability_from_logs(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    log = first_log(logs, "ABILITY_ACTIVATED")
    if not log:
        return {}

    refs = log.get("cardRefs") or []
    message = log.get("message") or ""
    ability_name = None
    match = re.search(r"\bactivated\s+(.+?)\s+on\s+", message, flags=re.IGNORECASE)
    if match:
        ability_name = match.group(1).strip()

    result: Dict[str, Any] = {"ability_name": ability_name, "derived_from_logs": True}
    if refs:
        result["card_id"] = refs[0].get("id")
        result["card_name"] = refs[0].get("name")
    return result


def infer_ability_from_compact_logs(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    for log in logs:
        if log.get("type") != "ABILITY_ACTIVATED":
            continue

        refs = log.get("cards") or []
        message = log.get("message") or ""
        ability_name = None
        match = re.search(r"\bactivated\s+(.+?)\s+on\s+", message, flags=re.IGNORECASE)
        if match:
            ability_name = match.group(1).strip()

        result: Dict[str, Any] = {
            "ability_name": ability_name,
            "derived_from_logs": True,
        }
        if refs:
            result["card_id"] = refs[0].get("id")
            result["card_name"] = refs[0].get("name")
        return result

    return {}


def choice_results(logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    choices: List[Dict[str, Any]] = []

    for log in logs:
        if log.get("type") != "CHOICE_RESOLVED":
            continue

        message = log.get("message") or ""
        refs = log.get("cardRefs") or []
        item: Dict[str, Any] = {
            "message": message,
            "cards": [{"id": x.get("id"), "name": x.get("name")} for x in refs],
        }

        if not refs:
            match = re.search(r"\bchose\s+(.+)$", message, flags=re.IGNORECASE)
            if match:
                item["option"] = match.group(1).strip().strip('"')

        choices.append(item)

    return choices


def prompt_summary(state: Dict[str, Any], responding_player: Any, perspective: Any) -> Dict[str, Any]:
    source = state.get("promptSourceCard")
    pending = state.get("pendingPrompts") or []

    # pendingPrompts represents the replay perspective's visible prompts.
    visible_prompts = []
    if responding_player == perspective:
        for prompt in pending:
            if not isinstance(prompt, dict):
                continue
            visible_prompts.append(
                {
                    "id": prompt.get("id"),
                    "type": prompt.get("type"),
                    "message": prompt.get("message"),
                    "required": prompt.get("required"),
                    "min_select": prompt.get("minSelect"),
                    "max_select": prompt.get("maxSelect"),
                    "valid_targets": copy.deepcopy(prompt.get("validTargets")),
                    "source_card_instance_id": prompt.get("sourceCardInstanceId"),
                    "source_ability": prompt.get("sourceAbility"),
                    "params": copy.deepcopy(prompt.get("params")),
                }
            )

    return {
        "source_card": card_summary(source) if isinstance(source, dict) else None,
        "visible_prompts": visible_prompts,
        "opponent_has_pending_prompts": state.get("opponentHasPendingPrompts"),
    }



def find_card_in_state(state: Dict[str, Any], instance_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Find one card instance in visible reconstructed state.

    Challenges can move a card from field -> discard, so search the common
    visible zones rather than only the field. Inkwell entries wrap cards in a
    `card` object and are handled separately.
    """

    if not instance_id:
        return None

    for player_key, owner_label in (("myPlayer", "perspective"), ("opponent", "opponent")):
        player = state.get(player_key) or {}

        for zone in ("field", "items", "hand", "discard"):
            for card in player.get(zone) or []:
                if isinstance(card, dict) and card.get("instanceId") == instance_id:
                    return {
                        "owner": owner_label,
                        "zone": zone,
                        "card": card_summary(card),
                    }

        for entry in player.get("inkwell") or []:
            if not isinstance(entry, dict):
                continue
            card = entry.get("card")
            if isinstance(card, dict) and card.get("instanceId") == instance_id:
                return {
                    "owner": owner_label,
                    "zone": "inkwell",
                    "card": card_summary(card),
                }

    return None


def challenge_from_frame(
    taken: Dict[str, Any],
    frame_logs: List[Dict[str, Any]],
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize a Duels ATTACK frame.

    Duels names the frame ATTACK but records `takenAction.type == CHALLENGE`.
    The takenAction contains the core result, while the detailed CARD_ATTACK
    resolution log contains Challenger/Resist and total-damage math.
    """

    attacker_instance = taken.get("attackerInstanceId")
    defender_instance = taken.get("defenderInstanceId")

    result: Dict[str, Any] = {
        "attacker": {
            "card_id": taken.get("attackerCardId"),
            "instance_id": attacker_instance,
            "name": taken.get("attackerName"),
            "before": find_card_in_state(before, attacker_instance),
            "after": find_card_in_state(after, attacker_instance),
        },
        "defender": {
            "card_id": taken.get("defenderCardId"),
            "instance_id": defender_instance,
            "name": taken.get("defenderName"),
            "before": find_card_in_state(before, defender_instance),
            "after": find_card_in_state(after, defender_instance),
        },
        "damage_to_defender": taken.get("damageToDefender"),
        "damage_to_attacker": taken.get("damageToAttacker"),
        "defender_banished": taken.get("defenderBanished"),
        "attacker_banished": taken.get("attackerBanished"),
    }

    attacker_banished = bool(result.get("attacker_banished"))
    defender_banished = bool(result.get("defender_banished"))

    if attacker_banished and defender_banished:
        result["outcome"] = "mutual_banish"
    elif defender_banished:
        result["outcome"] = "defender_banished"
    elif attacker_banished:
        result["outcome"] = "attacker_banished"
    else:
        result["outcome"] = "neither_banished"

    # Duels emits two CARD_ATTACK logs per challenge. The second has the
    # detailed combat calculation; prefer the one containing attackerBaseStrength.
    resolution_log = None
    for log in frame_logs:
        if log.get("type") != "CARD_ATTACK":
            continue
        data = log.get("data") or {}
        if "attackerBaseStrength" in data:
            resolution_log = log

    if resolution_log:
        data = resolution_log.get("data") or {}
        result["combat_math"] = {
            "attacker_base_strength": data.get("attackerBaseStrength"),
            "attacker_challenger_bonus": data.get("attackerChallengerBonus"),
            "raw_damage_to_defender": data.get("rawDamageToDefender"),
            "actual_damage_to_defender": data.get("actualDamageToDefender"),
            "defender_resist_reduction": data.get("defenderResistReduction"),
            "defender_willpower": data.get("defenderWillpower"),
            "defender_total_damage": data.get("defenderTotalDamage"),
            "raw_damage_to_attacker": data.get("rawDamageToAttacker"),
            "actual_damage_to_attacker": data.get("actualDamageToAttacker"),
            "attacker_resist_reduction": data.get("attackerResistReduction"),
            "attacker_willpower": data.get("attackerWillpower"),
            "attacker_total_damage": data.get("attackerTotalDamage"),
        }
        result["resolution_message"] = resolution_log.get("message")
    else:
        result["combat_math"] = None
        result["resolution_message"] = None

    return result


def compare_hands(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> Dict[str, Any]:
    before_by_instance = {
        c.get("instanceId"): c for c in before if isinstance(c, dict) and c.get("instanceId")
    }
    after_by_instance = {
        c.get("instanceId"): c for c in after if isinstance(c, dict) and c.get("instanceId")
    }

    before_ids = set(before_by_instance)
    after_ids = set(after_by_instance)

    kept = before_ids & after_ids
    sent_back = before_ids - after_ids
    drawn = after_ids - before_ids

    return {
        "kept": [card_summary(c) for c in before if c.get("instanceId") in kept],
        "sent_back": [card_summary(c) for c in before if c.get("instanceId") in sent_back],
        "drawn": [card_summary(c) for c in after if c.get("instanceId") in drawn],
    }


def mulligan_from_log(logs: List[Dict[str, Any]], perspective: int) -> Optional[Dict[str, Any]]:
    for log in logs:
        if log.get("type") != "MULLIGAN" or log.get("player") != perspective:
            continue

        count = (log.get("data") or {}).get("mulliganCount")
        refs = log.get("cardRefs") or []
        if not isinstance(count, int):
            return None

        return {
            "count": count,
            "sent_back": [
                {"id": ref.get("id"), "name": ref.get("name")}
                for ref in refs[:count]
            ],
            "drawn": [
                {"id": ref.get("id"), "name": ref.get("name")}
                for ref in refs[count : count * 2]
            ],
            "source": "MULLIGAN log",
        }

    return None


def get_frame_logs(
    all_logs: List[Dict[str, Any]],
    previous_count: int,
    current_count: Any,
    warnings: List[str],
    seq: Any,
) -> Tuple[List[Dict[str, Any]], int]:
    if not isinstance(current_count, int):
        return [], previous_count

    if current_count < previous_count:
        warnings.append(
            f"Frame {seq}: logCountAfter decreased from {previous_count} to {current_count}; "
            "frame log slice omitted."
        )
        return [], current_count

    if current_count > len(all_logs):
        warnings.append(
            f"Frame {seq}: logCountAfter={current_count} exceeds total logs={len(all_logs)}; clamped."
        )
        current_count = len(all_logs)

    return all_logs[previous_count:current_count], current_count


# ---------------------------------------------------------------------------
# Main normalization
# ---------------------------------------------------------------------------

def parse_replay(replay: Dict[str, Any]) -> Dict[str, Any]:
    if replay.get("format") != "duels-replay-v1":
        raise ValueError(f"Unsupported replay format: {replay.get('format')!r}")

    perspective = replay.get("perspective")
    names = replay.get("playerNames") or {}
    frames = replay.get("frames") or []
    logs = replay.get("logs") or []

    state = copy.deepcopy(replay.get("baseSnapshot") or {})
    initial_state = copy.deepcopy(state)
    previous_log_count = replay.get("baseSnapshotLogCount") or 0

    parser_warnings: List[str] = []
    actions: List[Dict[str, Any]] = []
    undo_ranges: List[Dict[str, Any]] = []
    first_player = None
    perspective_mulligan: Optional[Dict[str, Any]] = None

    # Logs are the cleanest source of "mulliganed X; drew Y" and are used as
    # a cross-check against state reconstruction.
    logged_mulligan = mulligan_from_log(logs, perspective)

    for frame in frames:
        seq = frame.get("seq")
        raw_type = frame.get("actionType") or "UNKNOWN"
        actor = frame.get("player")

        before = copy.deepcopy(state)
        frame_logs, previous_log_count = get_frame_logs(
            logs,
            previous_log_count,
            frame.get("logCountAfter"),
            parser_warnings,
            seq,
        )

        try:
            state = apply_duels_patch(state, frame.get("patch") or [])
        except Exception as exc:
            raise RuntimeError(
                f"Failed applying patch for seq={seq} actionType={raw_type}: {exc}"
            ) from exc

        after = copy.deepcopy(state)

        # firstPlayer in baseSnapshot is not authoritative in the supplied
        # replay. The CHOOSE_STARTING_PLAYER frame changes it to the real value.
        if raw_type == "CHOOSE_STARTING_PLAYER":
            first_player = after.get("firstPlayer")

        # The state *before* an action is the right source of the current turn.
        # END_TURN patches can increment turnNumber before the next player acts,
        # and frame.turnNumber may already reflect that increment.
        gameplay_turn = before.get("turnNumber") if before.get("status") == "playing" else None
        active_player = before.get("currentPlayer") if before.get("status") == "playing" else None

        if raw_type == "MULLIGAN" and actor == perspective:
            reconstructed = compare_hands(
                (before.get("myPlayer") or {}).get("hand") or [],
                (after.get("myPlayer") or {}).get("hand") or [],
            )
            reconstructed["count"] = len(reconstructed["sent_back"])
            reconstructed["source"] = "state diff"
            perspective_mulligan = reconstructed

            if logged_mulligan and logged_mulligan.get("count") != reconstructed.get("count"):
                parser_warnings.append(
                    "Perspective mulligan count differs between MULLIGAN log and reconstructed state."
                )

        undo_match = re.fullmatch(r"FREE_UNDO:(\d+)", raw_type)
        if undo_match:
            target_seq = int(undo_match.group(1))
            undo = {
                "undo_seq": seq,
                "target_seq": target_seq,
                "invalidated_through_seq": (seq - 1) if isinstance(seq, int) else None,
            }
            undo_ranges.append(undo)

            for prior in actions:
                prior_seq = prior.get("seq")
                if isinstance(prior_seq, int) and target_seq <= prior_seq < seq:
                    prior["undone"] = True
                    prior["undone_by_seq"] = seq

            actions.append(
                {
                    "seq": seq,
                    "raw_type": raw_type,
                    "type": "undo",
                    "actor": actor,
                    "actor_name": player_name(names, actor),
                    "actor_is_perspective": actor == perspective,
                    "gameplay_turn": gameplay_turn,
                    "duels_frame_turn_number": frame.get("turnNumber"),
                    "undo": undo,
                    "undone": False,
                    "logs": compact_logs(frame_logs),
                    "coach_context": state_summary(before) if actor == perspective else None,
                }
            )
            continue

        taken = copy.deepcopy(frame.get("takenAction") or {})

        action: Dict[str, Any] = {
            "seq": seq,
            "raw_type": raw_type,
            "type": NORMALIZED_TYPES.get(raw_type, raw_type.lower()),
            "actor": actor,
            "actor_name": player_name(names, actor),
            "actor_is_perspective": actor == perspective,
            "active_player": active_player,
            "active_player_name": player_name(names, active_player),
            "gameplay_turn": gameplay_turn,
            "duels_frame_turn_number": frame.get("turnNumber"),
            "card_id": taken.get("cardId"),
            "card_instance_id": taken.get("cardInstanceId"),
            "card_name": taken.get("cardName"),
            "card_type": taken.get("cardType"),
            "source": taken.get("source"),
            "ability_name": taken.get("abilityName") or None,
            "lore_gained": taken.get("loreGained"),
            "new_lore_total": taken.get("newLoreTotal"),
            "raw_taken_action": taken,
            "undone": False,
            "logs": compact_logs(frame_logs),
            # Only perspective-player decisions need repeated full decision context.
            # Opponent actions remain in the timeline, and the next perspective
            # action's context reflects their consequences.
            "coach_context": state_summary(before) if actor == perspective else None,
        }

        if raw_type == "ATTACK":
            action["challenge"] = challenge_from_frame(taken, frame_logs, before, after)
            # Aliases keep generic action consumers useful without requiring
            # special knowledge of the challenge object.
            action["card_id"] = taken.get("attackerCardId")
            action["card_instance_id"] = taken.get("attackerInstanceId")
            action["card_name"] = taken.get("attackerName")
            action["target_card_id"] = taken.get("defenderCardId")
            action["target_instance_id"] = taken.get("defenderInstanceId")
            action["target_name"] = taken.get("defenderName")

        elif raw_type == "PLAY_CARD" and not action.get("card_name"):
            action.update(infer_play_from_logs(frame_logs))
        elif raw_type == "BOOST" and not action.get("card_name"):
            action.update(infer_boost_from_logs(frame_logs))
        elif raw_type == "ACTIVATE_ABILITY":
            inferred = infer_ability_from_logs(frame_logs)
            for key, value in inferred.items():
                if not action.get(key):
                    action[key] = value

        if raw_type == "RESPOND_TO_PROMPT":
            action["prompt"] = prompt_summary(before, actor, perspective)
            action["choices"] = choice_results(frame_logs)

        if raw_type == "MULLIGAN" and actor == perspective:
            action["mulligan"] = perspective_mulligan

        actions.append(action)

    # Some ability activations create an opponent/perspective prompt without
    # producing ABILITY_ACTIVATED until the following RESPOND_TO_PROMPT frame.
    # Fill those activations from immediate follow-up response logs when safe.
    for index, action in enumerate(actions):
        if action.get("raw_type") != "ACTIVATE_ABILITY" or action.get("card_name"):
            continue

        actor = action.get("actor")
        for follow in actions[index + 1 : index + 4]:
            if follow.get("raw_type") != "RESPOND_TO_PROMPT":
                break
            inferred = infer_ability_from_compact_logs(follow.get("logs") or [])
            if inferred:
                action.update({k: v for k, v in inferred.items() if v is not None})
                action["derived_from_followup_seq"] = follow.get("seq")
                break

    effective_actions = [a for a in actions if not a.get("undone")]

    if first_player is None:
        first_player = state.get("firstPlayer")
        parser_warnings.append("No CHOOSE_STARTING_PLAYER frame found; used reconstructed state firstPlayer.")

    final_winner = state.get("winner")
    if final_winner is not None and replay.get("winner") is not None and final_winner != replay.get("winner"):
        parser_warnings.append(
            f"Final reconstructed winner {final_winner} differs from replay winner {replay.get('winner')}."
        )

    return {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "game": {
            "game_id": replay.get("gameId"),
            "replay_id": (replay.get("baseSnapshot") or {}).get("replayId"),
            "replay_format": replay.get("format"),
            "created_at": replay.get("createdAt"),
            "perspective": perspective,
            "perspective_name": player_name(names, perspective),
            "player_names": names,
            "first_player": first_player,
            "winner": replay.get("winner"),
            "victory_reason": replay.get("victoryReason"),
            "turn_count": replay.get("turnCount"),
            "from_playground": replay.get("fromPlayground"),
        },
        "starting_hand": [
            card_summary(card)
            for card in ((initial_state.get("myPlayer") or {}).get("hand") or [])
        ],
        "decklist": replay.get("decklist") or [],
        "mulligan": perspective_mulligan,
        "mulligan_log": logged_mulligan,
        "undo_ranges": undo_ranges,
        "actions": actions,
        "effective_actions": effective_actions,
        "final_state": state_summary(state),
        "parser_warnings": parser_warnings,
    }


# ---------------------------------------------------------------------------
# CLI / readable validation output
# ---------------------------------------------------------------------------

def find_default_replay() -> Path:
    files = sorted(
        DEFAULT_PROBE_DIR.glob("*.replay.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise SystemExit("No .replay.json files found in data/duels/raw/")
    return files[0]


def print_card_list(cards: List[Dict[str, Any]]) -> None:
    if not cards:
        print("    <none>")
        return
    for card in cards:
        print(f"    {card.get('name')} [{card.get('id')}]")


def print_summary(parsed: Dict[str, Any]) -> None:
    game = parsed["game"]

    print("=" * 78)
    print("NORMALIZED DUELS REPLAY")
    print("=" * 78)
    print(f"Game:        {game['game_id']}")
    print(f"Perspective: P{game['perspective']} {game['perspective_name']}")
    print(f"First:       P{game['first_player']}")
    print(f"Winner:      P{game['winner']}")
    print(f"Reason:      {game['victory_reason']}")

    print("\nSTARTING HAND")
    print("-" * 78)
    print_card_list(parsed["starting_hand"])

    print("\nMULLIGAN")
    print("-" * 78)
    mulligan = parsed.get("mulligan")
    if not mulligan:
        print("  Unable to reconstruct perspective mulligan.")
    else:
        print(f"  Count: {mulligan.get('count')}")
        print("  KEPT")
        print_card_list(mulligan.get("kept") or [])
        print("  SENT BACK")
        print_card_list(mulligan.get("sent_back") or [])
        print("  DREW")
        print_card_list(mulligan.get("drawn") or [])

    if parsed.get("mulligan_log"):
        print(f"  Log cross-check count: {parsed['mulligan_log'].get('count')}")

    if parsed["undo_ranges"]:
        print("\nUNDOS")
        print("-" * 78)
        for undo in parsed["undo_ranges"]:
            print(
                f"  Seq {undo['undo_seq']} rolled back "
                f"{undo['target_seq']}–{undo['invalidated_through_seq']}"
            )

    print("\nEFFECTIVE TIMELINE")
    print("-" * 78)
    for action in parsed["effective_actions"]:
        if action.get("raw_type") == "GAME_FINISH":
            continue

        turn = (
            f"T{action['gameplay_turn']}"
            if action.get("gameplay_turn") is not None
            else "SETUP"
        )
        actor = action.get("actor")
        card = action.get("card_name") or ""
        ability = action.get("ability_name")
        extra = f" [{ability}]" if ability else ""

        if action.get("raw_type") == "ATTACK" and action.get("challenge"):
            challenge = action["challenge"]
            attacker = (challenge.get("attacker") or {}).get("name") or "?"
            defender = (challenge.get("defender") or {}).get("name") or "?"
            damage_out = challenge.get("damage_to_defender")
            damage_back = challenge.get("damage_to_attacker")
            outcome = challenge.get("outcome") or "?"
            display = (
                f"{attacker} -> {defender} "
                f"[{damage_out} dealt / {damage_back} taken; {outcome}]"
            )
        else:
            display = f"{card}{extra}"

        print(
            f"{str(action.get('seq')):>3}  "
            f"{turn:<6} "
            f"P{str(actor):<4} "
            f"{action.get('raw_type', ''):<24} "
            f"{display}"
        )

        if action.get("raw_type") == "RESPOND_TO_PROMPT":
            for choice in action.get("choices") or []:
                selected = ", ".join(c.get("name") or "?" for c in choice.get("cards") or [])
                if not selected:
                    selected = choice.get("option") or choice.get("message") or "?"
                print(f"       ↳ choice: {selected}")

    if parsed.get("parser_warnings"):
        print("\nPARSER WARNINGS")
        print("-" * 78)
        for warning in parsed["parser_warnings"]:
            print(f"  - {warning}")
    else:
        print("\nParser warnings: none")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize a Duels.ink replay JSON file")
    parser.add_argument(
        "replay",
        nargs="?",
        type=Path,
        help="Path to .replay.json. Defaults to newest file in data/duels/raw/.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for normalized JSON output (default: data/duels/normalized)",
    )
    args = parser.parse_args()

    replay_path = args.replay or find_default_replay()
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    parsed = parse_replay(replay)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{parsed['game']['game_id']}.normalized.json"
    output_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")

    print_summary(parsed)
    print(f"\nSaved normalized replay: {output_path}")


if __name__ == "__main__":
    main()
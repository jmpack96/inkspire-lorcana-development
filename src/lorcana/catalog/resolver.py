"""Conservative printing resolution. Names suggest candidates, never authorize aliases."""
from __future__ import annotations

from collections import defaultdict
import re
import unicodedata
from typing import Any, Iterable, Mapping

RESOLVER_VERSION = "printing-resolver-v1"
# Reviewed provider aliases: retain source IDs in replay data and evidence keys.
# Target identity includes the subtitle. No arbitrary name-only fallback.
REVIEWED_ALIASES = {
    "3-223": {
        "name": "Piglet - Pooh Pirate Captain",
        "review": "Team operator confirmed Duels 3-223 is the special-art printing, 2026-09-19.",
    },
}


def normalized_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.translate(str.maketrans({"–": "-", "—": "-", "’": "'"}))
    return re.sub(r"\s+", " ", value).strip().casefold()


def card_stats(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("raw") or {}
    source = raw.get("source_raw") or raw
    return {key: source.get(key) for key in ("strength", "willpower", "lore", "move_cost")}


def fingerprint(row: Mapping[str, Any]) -> tuple:
    return (
        normalized_name(row["name"]), tuple(sorted(row.get("ink_colors") or [])),
        row.get("cost"), row.get("inkable"), (row.get("card_type") or "").casefold(),
        tuple(sorted(row.get("classifications") or [])), row.get("rules_text"),
        tuple(card_stats(row).values()),
    )


def collect_names(value: Any, output: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    output = output if output is not None else defaultdict(set)
    if isinstance(value, dict):
        card_id = value.get("card_id") or value.get("id")
        name = value.get("card_name") or value.get("name")
        if isinstance(card_id, str) and isinstance(name, str) and name.strip():
            output.setdefault(card_id, set()).add(normalized_name(name))
        for child in value.values():
            collect_names(child, output)
    elif isinstance(value, list):
        for child in value:
            collect_names(child, output)
    return output


def resolve_printings(
    card_ids: Iterable[str], names: Mapping[str, set[str]], rows: Iterable[Mapping[str, Any]],
    aliases: Mapping[str, Mapping[str, str]] = REVIEWED_ALIASES,
) -> tuple[dict[str, dict], dict[str, dict]]:
    by_id = {row["card_id"]: dict(row) for row in rows}
    by_name: dict[str, list[dict]] = defaultdict(list)
    for row in by_id.values():
        by_name[normalized_name(row["name"])].append(row)
    resolved, decisions = {}, {}
    for card_id in sorted(set(card_ids)):
        observed = names.get(card_id, set())
        row = by_id.get(card_id)
        if row is not None:
            if observed and observed != {normalized_name(row["name"])}:
                decisions[card_id] = {"status": "identity_conflict"}
                continue
            resolved[card_id] = row
            decisions[card_id] = {"status": "exact", "canonical_card_id": card_id}
            continue
        alias = aliases.get(card_id)
        if alias is None:
            suggestions = sorted({r["card_id"] for n in observed for r in by_name.get(n, [])})
            decisions[card_id] = {"status": "unresolved", "candidate_ids": suggestions}
            continue
        expected = normalized_name(alias["name"])
        candidates = by_name.get(expected, [])
        if observed != {expected}:
            decisions[card_id] = {"status": "alias_identity_unconfirmed"}
        elif not candidates:
            decisions[card_id] = {"status": "alias_target_missing"}
        elif len({fingerprint(r) for r in candidates}) != 1:
            decisions[card_id] = {"status": "ambiguous_gameplay_data"}
        else:
            # Prefer a low collector number; IDs remain snapshot-specific provenance.
            row = min(candidates, key=lambda r: (
                int(r["collector_number"]) if str(r.get("collector_number", "")).isdigit() else 10**9,
                r["card_id"],
            ))
            resolved[card_id] = row
            decisions[card_id] = {
                "status": "reviewed_alias", "canonical_card_id": row["card_id"],
                "review": alias["review"],
            }
    return resolved, decisions

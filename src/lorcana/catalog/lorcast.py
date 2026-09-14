"""Lorcast adapter for periodic card-fact snapshots.

Lorcast is never queried during Coach analysis. This adapter downloads a
complete English card snapshot, converts provider records to our stable
set-number identifiers used by Duels (for example ``12-11``), and hands the
result to CatalogService for immutable persistence.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

LORCAST_API_ROOT = "https://api.lorcast.com/v0"


class LorcastError(RuntimeError):
    pass


class LorcastClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
        request_delay_seconds: float = 0.075,
        max_attempts: int = 4,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds must be non-negative")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.session = session or requests.Session()
        self._owns_session = session is None
        self.timeout_seconds = timeout_seconds
        self.request_delay_seconds = request_delay_seconds
        self.max_attempts = max_attempts
        self.sleeper = sleeper

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def _get_json(self, path: str) -> Any:
        url = f"{LORCAST_API_ROOT}{path}"
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    raise LorcastError(f"Lorcast transient HTTP {response.status_code}")
                if response.status_code != 200:
                    raise LorcastError(f"Lorcast HTTP {response.status_code} for {path}")
                return response.json()
            except (requests.RequestException, ValueError, LorcastError) as error:
                last_error = error
                if attempt >= self.max_attempts:
                    break
                self.sleeper(min(2 ** (attempt - 1), 8))
        raise LorcastError(f"Lorcast request failed for {path}: {last_error}") from last_error

    def sets(self) -> list[dict[str, Any]]:
        payload = self._get_json("/sets")
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise LorcastError("Lorcast /sets returned an unexpected payload")
        return rows

    def cards_for_set(self, set_code: str) -> list[dict[str, Any]]:
        payload = self._get_json(f"/sets/{set_code}/cards")
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise LorcastError(f"Lorcast cards for set {set_code} returned an unexpected payload")
        return payload

    def complete_english_snapshot(self) -> tuple[dict[str, Any], dict[str, Any]]:
        sets = self.sets()
        cards: list[dict[str, Any]] = []
        included_sets: list[dict[str, str | None]] = []
        for set_row in sets:
            code = str(set_row.get("code") or "").strip()
            if not code:
                raise LorcastError("Lorcast set is missing its code")
            # Lorcast asks clients to pace API requests; /sets was already one
            # request, so delay before every subsequent per-set fetch.
            if self.request_delay_seconds:
                self.sleeper(self.request_delay_seconds)
            raw_cards = self.cards_for_set(code)
            included_sets.append({
                "code": code,
                "name": _optional_text(set_row.get("name")),
                "released_at": _optional_text(set_row.get("released_at")),
            })
            for raw in raw_cards:
                if str(raw.get("lang") or "en").lower() != "en":
                    continue
                cards.append(_map_lorcast_card(raw, fallback_set=set_row))
        cards.sort(key=lambda row: row["id"])
        return {"cards": cards}, {"sets": included_sets, "set_count": len(included_sets)}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _colors(raw: dict[str, Any]) -> list[str]:
    value = raw.get("inks", raw.get("ink"))
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise LorcastError(f"Unexpected Lorcast ink value for card {raw.get('id')}")


def _map_lorcast_card(raw: dict[str, Any], *, fallback_set: dict[str, Any]) -> dict[str, Any]:
    set_data = raw.get("set") if isinstance(raw.get("set"), dict) else fallback_set
    set_code = _optional_text(set_data.get("code"))
    collector_number = _optional_text(raw.get("collector_number"))
    base_name = _optional_text(raw.get("name"))
    version = _optional_text(raw.get("version"))
    if not set_code or not collector_number or not base_name:
        raise LorcastError("Lorcast card is missing set code, collector number, or name")
    display_name = f"{base_name} - {version}" if version else base_name
    raw_type = raw.get("type")
    if isinstance(raw_type, list):
        card_type = "/".join(str(value).strip() for value in raw_type if str(value).strip()) or None
    else:
        card_type = _optional_text(raw_type)
    return {
        "id": f"{set_code}-{collector_number}",
        "name": display_name,
        "version": version,
        "set_code": set_code,
        "set_name": _optional_text(set_data.get("name")),
        "collector_number": collector_number,
        "ink_colors": _colors(raw),
        "cost": raw.get("cost"),
        "inkable": raw.get("inkwell"),
        "classifications": raw.get("classifications") or [],
        "card_type": card_type,
        "rules_text": raw.get("text"),
        "source_id": raw.get("id"),
        "source_raw": raw,
    }

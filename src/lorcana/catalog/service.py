"""Immutable catalog snapshot ingestion and fact lookup."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, ContextManager
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection, Engine

from lorcana.catalog.repository import CatalogRepository
from lorcana.db.tx import transaction

Clock = Callable[[], datetime]
UUIDFactory = Callable[[], UUID]
TransactionFactory = Callable[[], ContextManager[Connection]]
ReadConnectionFactory = Callable[[], ContextManager[Connection]]


@dataclass(frozen=True)
class CatalogImportResult:
    snapshot_id: UUID
    created: bool
    card_count: int
    source_sha256: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_card(card: Mapping[str, Any]) -> dict[str, Any]:
    card_id = _optional_text(card.get("id") or card.get("card_id"))
    name = _optional_text(card.get("name"))
    if not card_id or not name:
        raise ValueError("Every catalog card requires id/card_id and name")
    colors = card.get("ink_colors", card.get("colors", []))
    if colors is None:
        colors = []
    if not isinstance(colors, list) or not all(isinstance(value, str) for value in colors):
        raise ValueError(f"Catalog card {card_id} ink_colors/colors must be a string list")
    classifications = card.get("classifications", [])
    if classifications is None:
        classifications = []
    if not isinstance(classifications, list) or not all(isinstance(value, str) for value in classifications):
        raise ValueError(f"Catalog card {card_id} classifications must be a string list")
    cost = card.get("cost")
    if cost is not None:
        if isinstance(cost, bool):
            raise ValueError(f"Catalog card {card_id} cost must be an integer")
        cost = int(cost)
    inkable = card.get("inkable")
    if inkable is not None and not isinstance(inkable, bool):
        raise ValueError(f"Catalog card {card_id} inkable must be boolean")
    return {
        "card_id": card_id,
        "name": name,
        "version": _optional_text(card.get("version") or card.get("subtitle")),
        "set_code": _optional_text(card.get("set_code")),
        "set_name": _optional_text(card.get("set_name")),
        "collector_number": _optional_text(card.get("collector_number")),
        "ink_colors": [value.strip().lower() for value in colors if value.strip()],
        "cost": cost,
        "inkable": inkable,
        "classifications": [value.strip() for value in classifications if value.strip()],
        "card_type": _optional_text(card.get("card_type") or card.get("type")),
        "rules_text": _optional_text(card.get("rules_text") or card.get("text")),
        "raw": dict(card),
    }


class CatalogService:
    def __init__(
        self,
        *,
        repository: CatalogRepository,
        read_connection_factory: ReadConnectionFactory,
        transaction_factory: TransactionFactory,
        clock: Clock = utc_now,
        uuid_factory: UUIDFactory = uuid4,
    ) -> None:
        self.repository = repository
        self.read_connection_factory = read_connection_factory
        self.transaction_factory = transaction_factory
        self.clock = clock
        self.uuid_factory = uuid_factory

    @classmethod
    def from_engine(cls, engine: Engine, **kwargs: Any) -> "CatalogService":
        @contextmanager
        def reader():
            with engine.connect() as connection:
                yield connection
        return cls(
            repository=CatalogRepository(),
            read_connection_factory=reader,
            transaction_factory=lambda: transaction(engine),
            **kwargs,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CatalogService clock must return timezone-aware datetimes")
        return value.astimezone(timezone.utc)

    def import_snapshot(
        self,
        payload: Mapping[str, Any],
        *,
        source_name: str,
        source_version: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> CatalogImportResult:
        if not source_name.strip():
            raise ValueError("source_name must not be empty")
        raw_cards = payload.get("cards")
        if not isinstance(raw_cards, list) or not all(isinstance(card, dict) for card in raw_cards):
            raise ValueError("Catalog payload requires a cards list of objects")
        cards = [_normalize_card(card) for card in raw_cards]
        ids = [card["card_id"] for card in cards]
        if len(ids) != len(set(ids)):
            raise ValueError("Catalog snapshot contains duplicate card IDs")
        source_sha = _canonical_sha(payload)
        with self.read_connection_factory() as connection:
            existing = self.repository.get_snapshot_by_hash(connection, source_sha)
        if existing is not None:
            return CatalogImportResult(
                snapshot_id=existing["snapshot_id"],
                created=False,
                card_count=len(cards),
                source_sha256=source_sha,
            )
        snapshot_id = self.uuid_factory()
        with self.transaction_factory() as connection:
            self.repository.insert_snapshot(
                connection,
                snapshot_id=snapshot_id,
                source_name=source_name.strip(),
                source_version=_optional_text(source_version),
                source_sha256=source_sha,
                metadata_json=dict(metadata or {}),
                imported_at=self._now(),
                cards=cards,
            )
        return CatalogImportResult(snapshot_id, True, len(cards), source_sha)

    def latest_snapshot_id(self) -> UUID | None:
        with self.read_connection_factory() as connection:
            row = self.repository.latest_snapshot(connection)
        return None if row is None else row["snapshot_id"]

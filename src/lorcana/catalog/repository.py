"""PostgreSQL repository for immutable card catalog snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from lorcana.db.schema.catalog import catalog_cards, catalog_snapshots


class CatalogRepository:
    def get_snapshot_by_hash(self, connection: Connection, source_sha256: str):
        return connection.execute(
            select(catalog_snapshots).where(catalog_snapshots.c.source_sha256 == source_sha256)
        ).mappings().one_or_none()

    def get_snapshot(self, connection: Connection, snapshot_id: UUID):
        return connection.execute(
            select(catalog_snapshots).where(catalog_snapshots.c.snapshot_id == snapshot_id)
        ).mappings().one_or_none()

    def latest_snapshot(self, connection: Connection):
        return connection.execute(
            select(catalog_snapshots)
            .order_by(catalog_snapshots.c.imported_at.desc(), catalog_snapshots.c.snapshot_id.desc())
            .limit(1)
        ).mappings().one_or_none()

    def insert_snapshot(
        self,
        connection: Connection,
        *,
        snapshot_id: UUID,
        source_name: str,
        source_version: str | None,
        source_sha256: str,
        metadata_json: Mapping[str, Any],
        imported_at: datetime,
        cards: Iterable[Mapping[str, Any]],
    ) -> None:
        connection.execute(
            catalog_snapshots.insert().values(
                snapshot_id=snapshot_id,
                source_name=source_name,
                source_version=source_version,
                source_sha256=source_sha256,
                metadata_json=dict(metadata_json),
                imported_at=imported_at,
            )
        )
        rows = [{**dict(card), "snapshot_id": snapshot_id} for card in cards]
        if rows:
            connection.execute(catalog_cards.insert(), rows)

    def cards_by_ids(self, connection: Connection, snapshot_id: UUID, card_ids: Iterable[str]):
        ids = sorted(set(card_ids))
        if not ids:
            return []
        return connection.execute(
            select(catalog_cards).where(
                catalog_cards.c.snapshot_id == snapshot_id,
                catalog_cards.c.card_id.in_(ids),
            )
        ).mappings().all()

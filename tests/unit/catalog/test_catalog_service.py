from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from lorcana.catalog.service import CatalogService

NOW = datetime(2026, 9, 13, 20, 30, tzinfo=timezone.utc)
SNAPSHOT = UUID("00000000-0000-0000-0000-000000000701")


class FakeRepository:
    def __init__(self):
        self.by_hash = {}
        self.snapshots = {}
        self.cards = {}

    def get_snapshot_by_hash(self, _c, digest):
        return self.by_hash.get(digest)

    def latest_snapshot(self, _c):
        if not self.snapshots:
            return None
        return sorted(self.snapshots.values(), key=lambda row: (row["imported_at"], str(row["snapshot_id"])), reverse=True)[0]

    def insert_snapshot(self, _c, *, cards, **values):
        row = dict(values)
        self.snapshots[values["snapshot_id"]] = row
        self.by_hash[values["source_sha256"]] = row
        self.cards[values["snapshot_id"]] = [dict(card) for card in cards]


@contextmanager
def connection():
    yield object()


def service(repo):
    return CatalogService(
        repository=repo,
        read_connection_factory=connection,
        transaction_factory=connection,
        clock=lambda: NOW,
        uuid_factory=lambda: SNAPSHOT,
    )


def payload():
    return {
        "cards": [
            {
                "id": "12-11",
                "name": "Hamm - Piggy Bank",
                "colors": ["Sapphire"],
                "cost": 2,
                "inkable": True,
                "classifications": ["Storyborn", "Ally"],
                "type": "Character",
                "text": "Example rules text",
            }
        ]
    }


def test_catalog_snapshot_is_content_addressed_and_normalized():
    repo = FakeRepository()
    first = service(repo).import_snapshot(payload(), source_name="fixture", source_version="set-12")
    second = service(repo).import_snapshot(payload(), source_name="fixture", source_version="set-12")

    assert first.created is True
    assert second.created is False
    assert first.snapshot_id == second.snapshot_id == SNAPSHOT
    assert first.source_sha256 == second.source_sha256
    assert len(repo.snapshots) == 1
    card = repo.cards[SNAPSHOT][0]
    assert card["card_id"] == "12-11"
    assert card["ink_colors"] == ["sapphire"]
    assert card["card_type"] == "Character"
    assert service(repo).latest_snapshot_id() == SNAPSHOT


def test_catalog_rejects_malformed_or_ambiguous_card_facts():
    repo = FakeRepository()
    with pytest.raises(ValueError, match="cards list"):
        service(repo).import_snapshot({}, source_name="fixture")
    with pytest.raises(ValueError, match="requires id/card_id and name"):
        service(repo).import_snapshot({"cards": [{"id": "1-1"}]}, source_name="fixture")
    with pytest.raises(ValueError, match="duplicate card IDs"):
        service(repo).import_snapshot(
            {"cards": [{"id": "1-1", "name": "A"}, {"id": "1-1", "name": "B"}]},
            source_name="fixture",
        )
    with pytest.raises(ValueError, match="inkable must be boolean"):
        service(repo).import_snapshot(
            {"cards": [{"id": "1-1", "name": "A", "inkable": "yes"}]},
            source_name="fixture",
        )

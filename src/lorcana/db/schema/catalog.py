"""Versioned card catalog snapshots used as Coach facts."""

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, PrimaryKeyConstraint, Table, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB

from lorcana.db.metadata import metadata


catalog_snapshots = Table(
    "catalog_snapshots",
    metadata,
    Column("snapshot_id", Uuid, primary_key=True),
    Column("source_name", Text, nullable=False),
    Column("source_version", Text),
    Column("source_sha256", Text, nullable=False, unique=True),
    Column("metadata_json", JSONB, nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Index("ix_catalog_snapshots_imported_at", "imported_at"),
)

catalog_cards = Table(
    "catalog_cards",
    metadata,
    Column("snapshot_id", Uuid, nullable=False),
    Column("card_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("version", Text),
    Column("set_code", Text),
    Column("set_name", Text),
    Column("collector_number", Text),
    Column("ink_colors", JSONB, nullable=False),
    Column("cost", Integer),
    Column("inkable", Boolean),
    Column("classifications", JSONB, nullable=False),
    Column("card_type", Text),
    Column("rules_text", Text),
    Column("raw", JSONB, nullable=False),
    PrimaryKeyConstraint("snapshot_id", "card_id", name="pk_catalog_cards"),
    Index("ix_catalog_cards_name", "name"),
)
from sqlalchemy import ForeignKeyConstraint  # noqa: E402
catalog_cards.append_constraint(
    ForeignKeyConstraint(["snapshot_id"], ["catalog_snapshots.snapshot_id"], name="fk_catalog_cards_snapshot_id")
)

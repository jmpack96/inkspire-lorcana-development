"""Persisted deck snapshots and structured Coach analyses."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from lorcana.db.metadata import metadata


decklists = Table(
    "decklists",
    metadata,
    Column("decklist_id", Uuid, primary_key=True),
    Column("member_id", Uuid, ForeignKey("members.member_id"), nullable=False),
    Column("catalog_snapshot_id", Uuid, ForeignKey("catalog_snapshots.snapshot_id")),
    Column("name", Text),
    Column("source", Text, nullable=False),
    Column("source_reference", Text),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_decklists_member_id", "member_id"),
)


decklist_cards = Table(
    "decklist_cards",
    metadata,
    Column("decklist_id", Uuid, ForeignKey("decklists.decklist_id"), nullable=False),
    Column("card_id", Text, nullable=False),
    Column("card_name", Text, nullable=False),
    Column("quantity", Integer, nullable=False),
    PrimaryKeyConstraint("decklist_id", "card_id", name="pk_decklist_cards"),
    CheckConstraint("quantity > 0", name="decklist_cards_quantity_positive"),
)


coach_analysis_runs = Table(
    "coach_analysis_runs",
    metadata,
    Column("analysis_run_id", Uuid, primary_key=True),
    Column("member_id", Uuid, ForeignKey("members.member_id"), nullable=False),
    Column("normalization_id", Uuid, ForeignKey("duels_normalizations.normalization_id"), nullable=False),
    Column("feature_set_id", Uuid, ForeignKey("duels_feature_sets.feature_set_id"), nullable=False),
    Column("catalog_snapshot_id", Uuid, ForeignKey("catalog_snapshots.snapshot_id"), nullable=False),
    Column("decklist_id", Uuid, ForeignKey("decklists.decklist_id")),
    Column("analyzer_provider", Text, nullable=False),
    Column("analyzer_model", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("analysis_config", JSONB, nullable=False),
    Column("input_sha256", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False, unique=True),
    Column("status", Text, nullable=False),
    Column("usage", JSONB),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("error_category", Text),
    Column("error_summary", Text),
    CheckConstraint(
        "status IN ('running','succeeded','failed')",
        name="coach_analysis_runs_status",
    ),
    Index("ix_coach_analysis_runs_member_id", "member_id"),
    Index("ix_coach_analysis_runs_normalization_id", "normalization_id"),
)


coach_findings = Table(
    "coach_findings",
    metadata,
    Column("finding_id", Uuid, primary_key=True),
    Column("analysis_run_id", Uuid, ForeignKey("coach_analysis_runs.analysis_run_id"), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("category", Text, nullable=False),
    Column("impact", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("claim_type", Text, nullable=False),
    Column("observation", Text, nullable=False),
    Column("recommendation", Text, nullable=False),
    Column("evidence_action_ids", JSONB, nullable=False),
    Column("evidence_turns", JSONB, nullable=False),
    Column("payload", JSONB, nullable=False),
    CheckConstraint("impact IN ('low','medium','high')", name="coach_findings_impact"),
    CheckConstraint("confidence >= 0 AND confidence <= 1", name="coach_findings_confidence"),
    CheckConstraint("claim_type IN ('fact','inference')", name="coach_findings_claim_type"),
    UniqueConstraint("analysis_run_id", "ordinal", name="uq_coach_findings_run_ordinal"),
    Index("ix_coach_findings_analysis_run_id", "analysis_run_id"),
)


coach_reports = Table(
    "coach_reports",
    metadata,
    Column("report_id", Uuid, primary_key=True),
    Column("analysis_run_id", Uuid, ForeignKey("coach_analysis_runs.analysis_run_id"), nullable=False, unique=True),
    Column("format", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

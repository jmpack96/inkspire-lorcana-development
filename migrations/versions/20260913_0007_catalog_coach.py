"""catalog and coach evidence

Revision ID: 20260913_0007
Revises: 20260913_0006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260913_0007"
down_revision: Union[str, Sequence[str], None] = "20260913_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_snapshots",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text()),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint("source_sha256", name="uq_catalog_snapshots_source_sha256"),
    )
    op.create_index("ix_catalog_snapshots_imported_at", "catalog_snapshots", ["imported_at"])

    op.create_table(
        "catalog_cards",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text()),
        sa.Column("set_code", sa.Text()),
        sa.Column("set_name", sa.Text()),
        sa.Column("collector_number", sa.Text()),
        sa.Column("ink_colors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cost", sa.Integer()),
        sa.Column("inkable", sa.Boolean()),
        sa.Column("classifications", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("card_type", sa.Text()),
        sa.Column("rules_text", sa.Text()),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["catalog_snapshots.snapshot_id"], name="fk_catalog_cards_snapshot_id"),
        sa.PrimaryKeyConstraint("snapshot_id", "card_id", name="pk_catalog_cards"),
    )
    op.create_index("ix_catalog_cards_name", "catalog_cards", ["name"])

    op.create_table(
        "decklists",
        sa.Column("decklist_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_snapshot_id", sa.Uuid()),
        sa.Column("name", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["members.member_id"]),
        sa.ForeignKeyConstraint(["catalog_snapshot_id"], ["catalog_snapshots.snapshot_id"]),
        sa.PrimaryKeyConstraint("decklist_id"),
    )
    op.create_index("ix_decklists_member_id", "decklists", ["member_id"])

    op.create_table(
        "decklist_cards",
        sa.Column("decklist_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.Column("card_name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="decklist_cards_quantity_positive"),
        sa.ForeignKeyConstraint(["decklist_id"], ["decklists.decklist_id"]),
        sa.PrimaryKeyConstraint("decklist_id", "card_id", name="pk_decklist_cards"),
    )

    op.create_table(
        "coach_analysis_runs",
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("normalization_id", sa.Uuid(), nullable=False),
        sa.Column("feature_set_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("decklist_id", sa.Uuid()),
        sa.Column("analyzer_provider", sa.Text(), nullable=False),
        sa.Column("analyzer_model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("analysis_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_sha256", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_category", sa.Text()),
        sa.Column("error_summary", sa.Text()),
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="coach_analysis_runs_status"),
        sa.ForeignKeyConstraint(["member_id"], ["members.member_id"]),
        sa.ForeignKeyConstraint(["normalization_id"], ["duels_normalizations.normalization_id"]),
        sa.ForeignKeyConstraint(["feature_set_id"], ["duels_feature_sets.feature_set_id"]),
        sa.ForeignKeyConstraint(["catalog_snapshot_id"], ["catalog_snapshots.snapshot_id"]),
        sa.ForeignKeyConstraint(["decklist_id"], ["decklists.decklist_id"]),
        sa.PrimaryKeyConstraint("analysis_run_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_coach_analysis_runs_idempotency_key"),
    )
    op.create_index("ix_coach_analysis_runs_member_id", "coach_analysis_runs", ["member_id"])
    op.create_index("ix_coach_analysis_runs_normalization_id", "coach_analysis_runs", ["normalization_id"])

    op.create_table(
        "coach_findings",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("impact", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("claim_type", sa.Text(), nullable=False),
        sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("evidence_action_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_turns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("impact IN ('low','medium','high')", name="coach_findings_impact"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="coach_findings_confidence"),
        sa.CheckConstraint("claim_type IN ('fact','inference')", name="coach_findings_claim_type"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["coach_analysis_runs.analysis_run_id"]),
        sa.PrimaryKeyConstraint("finding_id"),
        sa.UniqueConstraint("analysis_run_id", "ordinal", name="uq_coach_findings_run_ordinal"),
    )
    op.create_index("ix_coach_findings_analysis_run_id", "coach_findings", ["analysis_run_id"])

    op.create_table(
        "coach_reports",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["coach_analysis_runs.analysis_run_id"]),
        sa.PrimaryKeyConstraint("report_id"),
        sa.UniqueConstraint("analysis_run_id", name="uq_coach_reports_analysis_run_id"),
    )


def downgrade() -> None:
    op.drop_table("coach_reports")
    op.drop_table("coach_findings")
    op.drop_index("ix_coach_analysis_runs_normalization_id", table_name="coach_analysis_runs")
    op.drop_index("ix_coach_analysis_runs_member_id", table_name="coach_analysis_runs")
    op.drop_table("coach_analysis_runs")
    op.drop_table("decklist_cards")
    op.drop_index("ix_decklists_member_id", table_name="decklists")
    op.drop_table("decklists")
    op.drop_index("ix_catalog_cards_name", table_name="catalog_cards")
    op.drop_table("catalog_cards")
    op.drop_index("ix_catalog_snapshots_imported_at", table_name="catalog_snapshots")
    op.drop_table("catalog_snapshots")

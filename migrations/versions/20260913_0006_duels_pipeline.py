"""durable duels pipeline

Revision ID: 20260913_0006
Revises: 20260913_0005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260913_0006"
down_revision: Union[str, Sequence[str], None] = "20260913_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duels_connections",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("provider_account_id", sa.Text()),
        sa.Column("label", sa.Text()),
        sa.Column("credential_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("sync_cursor", sa.Text()),
        sa.Column("history_exhausted", sa.Boolean(), nullable=False),
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_category", sa.Text()),
        sa.Column("last_error_summary", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','inactive','auth_error')", name="duels_connections_status"),
        sa.ForeignKeyConstraint(["member_id"], ["members.member_id"]),
        sa.PrimaryKeyConstraint("connection_id"),
    )
    op.create_index("ix_duels_connections_member_id", "duels_connections", ["member_id"])
    op.create_index(
        "uq_duels_connections_provider_account_id",
        "duels_connections",
        ["provider_account_id"],
        unique=True,
        postgresql_where=sa.text("provider_account_id IS NOT NULL"),
    )

    op.create_table(
        "duels_games",
        sa.Column("game_id", sa.Text(), nullable=False),
        sa.Column("match_id", sa.Text()),
        sa.Column("match_format", sa.Text()),
        sa.Column("match_game_number", sa.Integer()),
        sa.Column("mode", sa.Text()),
        sa.Column("queue_id", sa.Text()),
        sa.Column("queue_name", sa.Text()),
        sa.Column("ranked", sa.Boolean()),
        sa.Column("season_id", sa.Text()),
        sa.Column("season_name", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("game_id"),
    )
    op.create_index("ix_duels_games_started_at", "duels_games", ["started_at"])
    op.create_index("ix_duels_games_match_id", "duels_games", ["match_id"])

    op.create_table(
        "duels_game_observations",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Text(), nullable=False),
        sa.Column("result", sa.Text()),
        sa.Column("went_first", sa.Boolean()),
        sa.Column("your_deck_colors", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("opponent_display_name", sa.Text()),
        sa.Column("opponent_deck_colors", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("provider_replay_id", sa.Text()),
        sa.Column("replay_url", sa.Text()),
        sa.Column("provider_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["duels_connections.connection_id"]),
        sa.ForeignKeyConstraint(["game_id"], ["duels_games.game_id"]),
        sa.PrimaryKeyConstraint("connection_id", "game_id", name="pk_duels_game_observations"),
    )
    op.create_index("ix_duels_game_observations_game_id", "duels_game_observations", ["game_id"])
    op.create_index("ix_duels_game_observations_replay_id", "duels_game_observations", ["provider_replay_id"])

    op.create_table(
        "duels_replays",
        sa.Column("replay_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Text(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider_replay_id", sa.Text()),
        sa.Column("perspective", sa.Integer()),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("content_encoding", sa.Text(), nullable=False),
        sa.Column("compressed_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("compressed_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("validation", postgresql.JSONB(astext_type=sa.Text())),
        sa.CheckConstraint("status IN ('valid','invalid')", name="duels_replays_status"),
        sa.ForeignKeyConstraint(["connection_id"], ["duels_connections.connection_id"]),
        sa.ForeignKeyConstraint(["game_id"], ["duels_games.game_id"]),
        sa.PrimaryKeyConstraint("replay_id"),
        sa.UniqueConstraint("connection_id", "game_id", "source_sha256", name="uq_duels_replays_connection_game_hash"),
    )
    op.create_index("ix_duels_replays_game_id", "duels_replays", ["game_id"])
    op.create_index("ix_duels_replays_connection_id", "duels_replays", ["connection_id"])

    op.create_table(
        "duels_normalizations",
        sa.Column("normalization_id", sa.Uuid(), nullable=False),
        sa.Column("replay_id", sa.Uuid(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalized_sha256", sa.Text(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('valid','invalid')", name="duels_normalizations_status"),
        sa.ForeignKeyConstraint(["replay_id"], ["duels_replays.replay_id"]),
        sa.PrimaryKeyConstraint("normalization_id"),
        sa.UniqueConstraint("replay_id", "parser_version", name="uq_duels_normalizations_replay_parser"),
    )
    op.create_index("ix_duels_normalizations_replay_id", "duels_normalizations", ["replay_id"])

    op.create_table(
        "duels_feature_sets",
        sa.Column("feature_set_id", sa.Uuid(), nullable=False),
        sa.Column("normalization_id", sa.Uuid(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("features_sha256", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["normalization_id"], ["duels_normalizations.normalization_id"]),
        sa.PrimaryKeyConstraint("feature_set_id"),
        sa.UniqueConstraint("normalization_id", "extractor_version", name="uq_duels_feature_sets_normalization_extractor"),
    )
    op.create_index("ix_duels_feature_sets_normalization_id", "duels_feature_sets", ["normalization_id"])


def downgrade() -> None:
    op.drop_table("duels_feature_sets")
    op.drop_table("duels_normalizations")
    op.drop_table("duels_replays")
    op.drop_table("duels_game_observations")
    op.drop_table("duels_games")
    op.drop_index("uq_duels_connections_provider_account_id", table_name="duels_connections")
    op.drop_index("ix_duels_connections_member_id", table_name="duels_connections")
    op.drop_table("duels_connections")

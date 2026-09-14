"""Duels account, game, replay, normalization, and feature tables."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from lorcana.db.metadata import metadata


duels_connections = Table(
    "duels_connections",
    metadata,
    Column("connection_id", Uuid, primary_key=True),
    Column("member_id", Uuid, ForeignKey("members.member_id"), nullable=False),
    Column("provider_account_id", Text),
    Column("label", Text),
    # Credential refs identify an application secret (for example
    # env:DUELS_API_TOKEN_JACOB); raw bearer tokens are never stored here.
    Column("credential_ref", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("sync_cursor", Text),
    Column("history_exhausted", Boolean, nullable=False),
    Column("last_sync_started_at", DateTime(timezone=True)),
    Column("last_sync_completed_at", DateTime(timezone=True)),
    Column("last_error_category", Text),
    Column("last_error_summary", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "status IN ('active','inactive','auth_error')",
        name="duels_connections_status",
    ),
    Index("ix_duels_connections_member_id", "member_id"),
)
Index(
    "uq_duels_connections_provider_account_id",
    duels_connections.c.provider_account_id,
    unique=True,
    postgresql_where=duels_connections.c.provider_account_id.is_not(None),
)


duels_games = Table(
    "duels_games",
    metadata,
    Column("game_id", Text, primary_key=True),
    Column("match_id", Text),
    Column("match_format", Text),
    Column("match_game_number", Integer),
    Column("mode", Text),
    Column("queue_id", Text),
    Column("queue_name", Text),
    Column("ranked", Boolean),
    Column("season_id", Text),
    Column("season_name", Text),
    Column("started_at", DateTime(timezone=True)),
    Column("ended_at", DateTime(timezone=True)),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Index("ix_duels_games_started_at", "started_at"),
    Index("ix_duels_games_match_id", "match_id"),
)


duels_game_observations = Table(
    "duels_game_observations",
    metadata,
    Column("connection_id", Uuid, ForeignKey("duels_connections.connection_id"), nullable=False),
    Column("game_id", Text, ForeignKey("duels_games.game_id"), nullable=False),
    Column("result", Text),
    Column("went_first", Boolean),
    Column("your_deck_colors", JSONB),
    Column("opponent_display_name", Text),
    Column("opponent_deck_colors", JSONB),
    Column("provider_replay_id", Text),
    Column("replay_url", Text),
    Column("provider_payload", JSONB, nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("connection_id", "game_id", name="pk_duels_game_observations"),
    Index("ix_duels_game_observations_game_id", "game_id"),
    Index("ix_duels_game_observations_replay_id", "provider_replay_id"),
)


duels_replays = Table(
    "duels_replays",
    metadata,
    Column("replay_id", Uuid, primary_key=True),
    Column("game_id", Text, ForeignKey("duels_games.game_id"), nullable=False),
    Column("connection_id", Uuid, ForeignKey("duels_connections.connection_id"), nullable=False),
    Column("provider_replay_id", Text),
    Column("perspective", Integer),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("source_sha256", Text, nullable=False),
    Column("content_encoding", Text, nullable=False),
    Column("compressed_bytes", LargeBinary, nullable=False),
    Column("compressed_size", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("validation", JSONB),
    CheckConstraint("status IN ('valid','invalid')", name="duels_replays_status"),
    UniqueConstraint(
        "connection_id",
        "game_id",
        "source_sha256",
        name="uq_duels_replays_connection_game_hash",
    ),
    Index("ix_duels_replays_game_id", "game_id"),
    Index("ix_duels_replays_connection_id", "connection_id"),
)


duels_normalizations = Table(
    "duels_normalizations",
    metadata,
    Column("normalization_id", Uuid, primary_key=True),
    Column("replay_id", Uuid, ForeignKey("duels_replays.replay_id"), nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("normalized", JSONB, nullable=False),
    Column("normalized_sha256", Text, nullable=False),
    Column("warnings", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('valid','invalid')", name="duels_normalizations_status"),
    UniqueConstraint("replay_id", "parser_version", name="uq_duels_normalizations_replay_parser"),
    Index("ix_duels_normalizations_replay_id", "replay_id"),
)


duels_feature_sets = Table(
    "duels_feature_sets",
    metadata,
    Column("feature_set_id", Uuid, primary_key=True),
    Column("normalization_id", Uuid, ForeignKey("duels_normalizations.normalization_id"), nullable=False),
    Column("extractor_version", Text, nullable=False),
    Column("features", JSONB, nullable=False),
    Column("features_sha256", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "normalization_id",
        "extractor_version",
        name="uq_duels_feature_sets_normalization_extractor",
    ),
    Index("ix_duels_feature_sets_normalization_id", "normalization_id"),
)

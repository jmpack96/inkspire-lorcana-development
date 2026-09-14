"""Immutable rating-run and publication tables."""

from sqlalchemy import (
    BigInteger,
    Boolean,
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

rating_runs = Table(
    "rating_runs",
    metadata,
    Column("rating_run_id", Uuid, primary_key=True),
    Column("algorithm", Text, nullable=False),
    Column("algorithm_version", Text, nullable=False),
    Column("policy_version", Text, nullable=False),
    Column("parameters", JSONB, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("status", Text, nullable=False),
    Column("input_count", Integer),
    Column("player_count", Integer),
    Column("ordered_input_digest", Text),
    Column("exclusion_counts", JSONB),
    Column("notes", Text),
    CheckConstraint(
        "status IN ('building','validated','published','failed')",
        name="rating_runs_status",
    ),
    Index("ix_rating_runs_completed_at", "completed_at"),
)

rating_run_inputs = Table(
    "rating_run_inputs",
    metadata,
    Column("rating_run_id", Uuid, ForeignKey("rating_runs.rating_run_id"), nullable=False),
    Column("sequence_number", Integer, nullable=False),
    Column("match_id", BigInteger, ForeignKey("playhub_matches.match_id"), nullable=False),
    Column("event_id", BigInteger, ForeignKey("playhub_events.event_id"), nullable=False),
    Column("event_start_datetime", DateTime(timezone=True), nullable=False),
    Column("phase_order", Integer, nullable=False),
    Column("round_number", Integer, nullable=False),
    Column("player1_id", BigInteger, ForeignKey("playhub_players.player_id"), nullable=False),
    Column("player2_id", BigInteger, ForeignKey("playhub_players.player_id"), nullable=False),
    Column("winner_id", BigInteger, ForeignKey("playhub_players.player_id")),
    Column("is_draw", Boolean, nullable=False),
    PrimaryKeyConstraint("rating_run_id", "sequence_number", name="pk_rating_run_inputs"),
    UniqueConstraint("rating_run_id", "match_id", name="uq_rating_run_inputs_run_match"),
    Index("ix_rating_run_inputs_match_id", "match_id"),
)

rating_history = Table(
    "rating_history",
    metadata,
    Column("rating_run_id", Uuid, ForeignKey("rating_runs.rating_run_id"), nullable=False),
    Column("sequence_number", Integer, nullable=False),
    Column("player_id", BigInteger, ForeignKey("playhub_players.player_id"), nullable=False),
    Column("match_id", BigInteger, ForeignKey("playhub_matches.match_id"), nullable=False),
    Column("event_id", BigInteger, ForeignKey("playhub_events.event_id"), nullable=False),
    Column("rating_before", Float, nullable=False),
    Column("rating_after", Float, nullable=False),
    Column("rating_change", Float, nullable=False),
    Column("opponent_id", BigInteger, ForeignKey("playhub_players.player_id"), nullable=False),
    Column("opponent_rating_before", Float, nullable=False),
    Column("result", Text, nullable=False),
    PrimaryKeyConstraint("rating_run_id", "sequence_number", "player_id", name="pk_rating_history"),
    CheckConstraint("result IN ('WIN','LOSS','DRAW')", name="rating_history_result"),
    Index("ix_rating_history_run_player", "rating_run_id", "player_id"),
    Index("ix_rating_history_match_id", "match_id"),
)

rating_current = Table(
    "rating_current",
    metadata,
    Column("rating_run_id", Uuid, ForeignKey("rating_runs.rating_run_id"), nullable=False),
    Column("player_id", BigInteger, ForeignKey("playhub_players.player_id"), nullable=False),
    Column("rating", Float, nullable=False),
    Column("matches_played", Integer, nullable=False),
    Column("wins", Integer, nullable=False),
    Column("losses", Integer, nullable=False),
    Column("draws", Integer, nullable=False),
    Column("peak_rating", Float, nullable=False),
    PrimaryKeyConstraint("rating_run_id", "player_id", name="pk_rating_current"),
    Index("ix_rating_current_run_rating", "rating_run_id", "rating"),
)

rating_publications = Table(
    "rating_publications",
    metadata,
    Column("publication_name", Text, primary_key=True),
    Column("rating_run_id", Uuid, ForeignKey("rating_runs.rating_run_id"), nullable=False),
    Column("previous_rating_run_id", Uuid, ForeignKey("rating_runs.rating_run_id")),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("published_by", Text),
    Index("ix_rating_publications_run_id", "rating_run_id"),
    Index("ix_rating_publications_previous_run_id", "previous_rating_run_id"),
)

"""platform foundation: Play Hub source and immutable ratings

Revision ID: 20260913_0001
Revises: None
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260913_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playhub_stores",
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("full_address", sa.Text()), sa.Column("city", sa.Text()),
        sa.Column("state_region", sa.Text()), sa.Column("country", sa.Text()),
        sa.Column("latitude", sa.Float()), sa.Column("longitude", sa.Float()),
        sa.Column("email", sa.Text()), sa.Column("website", sa.Text()),
        sa.Column("first_seen", sa.DateTime(timezone=True)), sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.Column("last_synced", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("store_id", name="pk_playhub_stores"),
    )
    op.create_table(
        "playhub_players",
        sa.Column("player_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("display_name", sa.Text()), sa.Column("username", sa.Text()),
        sa.Column("first_seen", sa.DateTime(timezone=True)), sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("player_id", name="pk_playhub_players"),
    )
    op.create_index("ix_playhub_players_display_name", "playhub_players", ["display_name"])
    op.create_index("ix_playhub_players_username", "playhub_players", ["username"])
    op.create_table(
        "playhub_events",
        sa.Column("event_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("store_id", sa.Text()), sa.Column("name", sa.Text(), nullable=False),
        sa.Column("start_datetime", sa.DateTime(timezone=True)), sa.Column("end_datetime", sa.DateTime(timezone=True)),
        sa.Column("timezone", sa.Text()), sa.Column("gameplay_format_id", sa.Text()), sa.Column("format", sa.Text()),
        sa.Column("event_format", sa.Text()), sa.Column("category", sa.Text()), sa.Column("display_status", sa.Text()),
        sa.Column("event_status", sa.Text()), sa.Column("lifecycle_status", sa.Text()),
        sa.Column("player_count", sa.Integer()), sa.Column("registered_user_count", sa.Integer()), sa.Column("capacity", sa.Integer()),
        sa.Column("event_is_online", sa.Boolean()), sa.Column("full_address", sa.Text()),
        sa.Column("latitude", sa.Float()), sa.Column("longitude", sa.Float()), sa.Column("source_url", sa.Text()),
        sa.Column("discovered_at", sa.DateTime(timezone=True)), sa.Column("last_synced", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["store_id"], ["playhub_stores.store_id"], name="fk_playhub_events_store_id_playhub_stores"),
        sa.PrimaryKeyConstraint("event_id", name="pk_playhub_events"),
    )
    op.create_index("ix_playhub_events_start_datetime", "playhub_events", ["start_datetime"])
    op.create_index("ix_playhub_events_gameplay_format_id", "playhub_events", ["gameplay_format_id"])
    op.create_index("ix_playhub_events_store_id", "playhub_events", ["store_id"])
    op.create_table(
        "playhub_phases",
        sa.Column("phase_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False), sa.Column("phase_name", sa.Text()),
        sa.Column("phase_order", sa.Integer()), sa.Column("round_type", sa.Text()), sa.Column("status", sa.Text()),
        sa.ForeignKeyConstraint(["event_id"], ["playhub_events.event_id"], name="fk_playhub_phases_event_id_playhub_events"),
        sa.PrimaryKeyConstraint("phase_id", name="pk_playhub_phases"),
    )
    op.create_index("ix_playhub_phases_event_id", "playhub_phases", ["event_id"])
    op.create_table(
        "playhub_rounds",
        sa.Column("round_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False), sa.Column("phase_id", sa.BigInteger()),
        sa.Column("round_number", sa.Integer()), sa.Column("round_type", sa.Text()), sa.Column("status", sa.Text()),
        sa.Column("pairings_status", sa.Text()), sa.Column("standings_status", sa.Text()),
        sa.Column("final_round_in_event", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["playhub_events.event_id"], name="fk_playhub_rounds_event_id_playhub_events"),
        sa.ForeignKeyConstraint(["phase_id"], ["playhub_phases.phase_id"], name="fk_playhub_rounds_phase_id_playhub_phases"),
        sa.PrimaryKeyConstraint("round_id", name="pk_playhub_rounds"),
    )
    op.create_index("ix_playhub_rounds_event_id", "playhub_rounds", ["event_id"])
    op.create_index("ix_playhub_rounds_phase_id", "playhub_rounds", ["phase_id"])
    op.create_table(
        "playhub_registrations",
        sa.Column("registration_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False), sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name_at_event", sa.Text()), sa.Column("registration_status", sa.Text()),
        sa.Column("matches_won", sa.Integer()), sa.Column("matches_lost", sa.Integer()), sa.Column("matches_drawn", sa.Integer()),
        sa.Column("match_points", sa.Integer()), sa.Column("placement", sa.Integer()),
        sa.Column("registered_at", sa.DateTime(timezone=True)), sa.Column("last_synced", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["event_id"], ["playhub_events.event_id"], name="fk_playhub_registrations_event_id_playhub_events"),
        sa.ForeignKeyConstraint(["player_id"], ["playhub_players.player_id"], name="fk_playhub_registrations_player_id_playhub_players"),
        sa.PrimaryKeyConstraint("registration_id", name="pk_playhub_registrations"),
        sa.UniqueConstraint("event_id", "player_id", name="uq_playhub_registrations_event_player"),
    )
    op.create_index("ix_playhub_registrations_event_id", "playhub_registrations", ["event_id"])
    op.create_index("ix_playhub_registrations_player_id", "playhub_registrations", ["player_id"])
    op.create_table(
        "playhub_matches",
        sa.Column("match_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False), sa.Column("round_id", sa.BigInteger(), nullable=False),
        sa.Column("player1_id", sa.BigInteger()), sa.Column("player2_id", sa.BigInteger()), sa.Column("participant_count", sa.Integer()),
        sa.Column("player1_score", sa.Integer()), sa.Column("player2_score", sa.Integer()), sa.Column("winner_id", sa.BigInteger()),
        sa.Column("status", sa.Text()), sa.Column("table_number", sa.Integer()),
        sa.Column("is_draw", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_intentional_draw", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_unintentional_draw", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_bye", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_loss", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_ghost_match", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_feature_match", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["event_id"], ["playhub_events.event_id"], name="fk_playhub_matches_event_id_playhub_events"),
        sa.ForeignKeyConstraint(["round_id"], ["playhub_rounds.round_id"], name="fk_playhub_matches_round_id_playhub_rounds"),
        sa.ForeignKeyConstraint(["player1_id"], ["playhub_players.player_id"], name="fk_playhub_matches_player1_id_playhub_players"),
        sa.ForeignKeyConstraint(["player2_id"], ["playhub_players.player_id"], name="fk_playhub_matches_player2_id_playhub_players"),
        sa.ForeignKeyConstraint(["winner_id"], ["playhub_players.player_id"], name="fk_playhub_matches_winner_id_playhub_players"),
        sa.PrimaryKeyConstraint("match_id", name="pk_playhub_matches"),
    )
    op.create_index("ix_playhub_matches_event_id", "playhub_matches", ["event_id"])
    op.create_index("ix_playhub_matches_round_id", "playhub_matches", ["round_id"])
    op.create_index("ix_playhub_matches_player1_id", "playhub_matches", ["player1_id"])
    op.create_index("ix_playhub_matches_player2_id", "playhub_matches", ["player2_id"])
    op.create_table(
        "playhub_discovery_runs",
        sa.Column("discovery_run_id", sa.Uuid(), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False), sa.Column("events_received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unique_events", sa.Integer(), server_default="0", nullable=False), sa.Column("duplicate_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.Text(), nullable=False), sa.Column("error_category", sa.Text()), sa.Column("error_summary", sa.Text()),
        sa.PrimaryKeyConstraint("discovery_run_id", name="pk_playhub_discovery_runs"),
    )
    op.create_table(
        "playhub_event_sync_state",
        sa.Column("event_id", sa.BigInteger(), nullable=False), sa.Column("state", sa.Text(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)), sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_category", sa.Text()), sa.Column("last_error_summary", sa.Text()), sa.Column("source_revision", sa.Text()),
        sa.CheckConstraint("state IN ('discovered','pending','syncing','complete','partial','no_results','failed')", name="ck_playhub_event_sync_state_playhub_event_sync_state_state"),
        sa.ForeignKeyConstraint(["event_id"], ["playhub_events.event_id"], name="fk_playhub_event_sync_state_event_id_playhub_events"),
        sa.PrimaryKeyConstraint("event_id", name="pk_playhub_event_sync_state"),
    )
    op.create_index("ix_playhub_event_sync_state_state", "playhub_event_sync_state", ["state"])
    op.create_table(
        "playhub_import_attempts",
        sa.Column("import_attempt_id", sa.Uuid(), nullable=False), sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.Uuid()), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("status", sa.Text(), nullable=False),
        sa.Column("rounds_expected", sa.Integer()), sa.Column("rounds_imported", sa.Integer()),
        sa.Column("registrations_found", sa.Integer()), sa.Column("matches_found", sa.Integer()), sa.Column("players_found", sa.Integer()),
        sa.Column("error_category", sa.Text()), sa.Column("error_summary", sa.Text()),
        sa.CheckConstraint("status IN ('running','complete','partial','no_results','failed')", name="ck_playhub_import_attempts_playhub_import_attempts_status"),
        sa.ForeignKeyConstraint(["event_id"], ["playhub_events.event_id"], name="fk_playhub_import_attempts_event_id_playhub_events"),
        sa.PrimaryKeyConstraint("import_attempt_id", name="pk_playhub_import_attempts"),
    )
    op.create_index("ix_playhub_import_attempts_event_id", "playhub_import_attempts", ["event_id"])
    op.create_index("ix_playhub_import_attempts_started_at", "playhub_import_attempts", ["started_at"])

    op.create_table(
        "rating_runs",
        sa.Column("rating_run_id", sa.Uuid(), nullable=False), sa.Column("algorithm", sa.Text(), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=False), sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False), sa.Column("input_count", sa.Integer()), sa.Column("player_count", sa.Integer()),
        sa.Column("ordered_input_digest", sa.Text()), sa.Column("exclusion_counts", postgresql.JSONB(astext_type=sa.Text())), sa.Column("notes", sa.Text()),
        sa.CheckConstraint("status IN ('building','validated','published','failed')", name="ck_rating_runs_rating_runs_status"),
        sa.PrimaryKeyConstraint("rating_run_id", name="pk_rating_runs"),
    )
    op.create_index("ix_rating_runs_completed_at", "rating_runs", ["completed_at"])
    op.create_table(
        "rating_run_inputs",
        sa.Column("rating_run_id", sa.Uuid(), nullable=False), sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.BigInteger(), nullable=False), sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("event_start_datetime", sa.DateTime(timezone=True)), sa.Column("phase_order", sa.Integer()), sa.Column("round_number", sa.Integer()),
        sa.ForeignKeyConstraint(["event_id"], ["playhub_events.event_id"], name="fk_rating_run_inputs_event_id_playhub_events"),
        sa.ForeignKeyConstraint(["match_id"], ["playhub_matches.match_id"], name="fk_rating_run_inputs_match_id_playhub_matches"),
        sa.ForeignKeyConstraint(["rating_run_id"], ["rating_runs.rating_run_id"], name="fk_rating_run_inputs_rating_run_id_rating_runs"),
        sa.PrimaryKeyConstraint("rating_run_id", "sequence_number", name="pk_rating_run_inputs"),
        sa.UniqueConstraint("rating_run_id", "match_id", name="uq_rating_run_inputs_run_match"),
    )
    op.create_index("ix_rating_run_inputs_match_id", "rating_run_inputs", ["match_id"])
    op.create_table(
        "rating_history",
        sa.Column("rating_run_id", sa.Uuid(), nullable=False), sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False), sa.Column("match_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False), sa.Column("rating_before", sa.Float(), nullable=False),
        sa.Column("rating_after", sa.Float(), nullable=False), sa.Column("rating_change", sa.Float(), nullable=False),
        sa.Column("opponent_id", sa.BigInteger(), nullable=False), sa.Column("opponent_rating_before", sa.Float(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.CheckConstraint("result IN ('WIN','LOSS','DRAW')", name="ck_rating_history_rating_history_result"),
        sa.ForeignKeyConstraint(["event_id"], ["playhub_events.event_id"], name="fk_rating_history_event_id_playhub_events"),
        sa.ForeignKeyConstraint(["match_id"], ["playhub_matches.match_id"], name="fk_rating_history_match_id_playhub_matches"),
        sa.ForeignKeyConstraint(["opponent_id"], ["playhub_players.player_id"], name="fk_rating_history_opponent_id_playhub_players"),
        sa.ForeignKeyConstraint(["player_id"], ["playhub_players.player_id"], name="fk_rating_history_player_id_playhub_players"),
        sa.ForeignKeyConstraint(["rating_run_id"], ["rating_runs.rating_run_id"], name="fk_rating_history_rating_run_id_rating_runs"),
        sa.PrimaryKeyConstraint("rating_run_id", "sequence_number", "player_id", name="pk_rating_history"),
    )
    op.create_index("ix_rating_history_run_player", "rating_history", ["rating_run_id", "player_id"])
    op.create_index("ix_rating_history_match_id", "rating_history", ["match_id"])
    op.create_table(
        "rating_current",
        sa.Column("rating_run_id", sa.Uuid(), nullable=False), sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False), sa.Column("matches_played", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False), sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("draws", sa.Integer(), nullable=False), sa.Column("peak_rating", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["playhub_players.player_id"], name="fk_rating_current_player_id_playhub_players"),
        sa.ForeignKeyConstraint(["rating_run_id"], ["rating_runs.rating_run_id"], name="fk_rating_current_rating_run_id_rating_runs"),
        sa.PrimaryKeyConstraint("rating_run_id", "player_id", name="pk_rating_current"),
    )
    op.create_index("ix_rating_current_run_rating", "rating_current", ["rating_run_id", "rating"])
    op.create_table(
        "rating_publications",
        sa.Column("publication_name", sa.Text(), nullable=False), sa.Column("rating_run_id", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False), sa.Column("published_by", sa.Text()),
        sa.ForeignKeyConstraint(["rating_run_id"], ["rating_runs.rating_run_id"], name="fk_rating_publications_rating_run_id_rating_runs"),
        sa.PrimaryKeyConstraint("publication_name", name="pk_rating_publications"),
    )
    op.create_index("ix_rating_publications_run_id", "rating_publications", ["rating_run_id"])


def downgrade() -> None:
    for table in [
        "rating_publications", "rating_current", "rating_history", "rating_run_inputs", "rating_runs",
        "playhub_import_attempts", "playhub_event_sync_state", "playhub_discovery_runs",
        "playhub_matches", "playhub_registrations", "playhub_rounds", "playhub_phases",
        "playhub_events", "playhub_players", "playhub_stores",
    ]:
        op.drop_table(table)

import pytest
from sqlalchemy import inspect

pytestmark = pytest.mark.integration


def test_migrations_create_foundation_schema(db_engine):
    tables = set(inspect(db_engine).get_table_names())
    assert {
        "alembic_version", "playhub_events", "playhub_players", "playhub_matches",
        "rating_runs", "rating_run_inputs", "rating_current", "rating_publications",
    } <= tables


def test_rating_input_snapshot_columns_are_not_nullable(db_engine):
    columns = {row["name"]: row for row in inspect(db_engine).get_columns("rating_run_inputs")}
    for name in ("event_start_datetime", "phase_order", "round_number", "player1_id", "player2_id", "is_draw"):
        assert columns[name]["nullable"] is False

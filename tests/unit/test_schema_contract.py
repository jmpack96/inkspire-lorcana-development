from sqlalchemy import Boolean, DateTime, Float

from lorcana.db.metadata import metadata
import lorcana.db.schema  # noqa: F401


def test_foundation_tables_are_registered():
    expected = {
        "playhub_stores", "playhub_events", "playhub_phases", "playhub_rounds",
        "playhub_players", "playhub_registrations", "playhub_matches",
        "playhub_discovery_runs", "playhub_import_attempts", "playhub_event_sync_state",
        "rating_runs", "rating_run_inputs", "rating_history", "rating_current", "rating_publications",
        "members", "teams", "team_memberships", "member_playhub_links", "discord_accounts",
        "jobs", "job_attempts", "scheduled_jobs",
        "duels_connections", "duels_games", "duels_game_observations",
        "duels_replays", "duels_normalizations", "duels_feature_sets",
        "catalog_snapshots", "catalog_cards",
        "decklists", "decklist_cards", "coach_analysis_runs", "coach_findings", "coach_reports",
        "discord_command_usage",
    }
    assert expected == set(metadata.tables)


def test_postgres_type_contracts_are_explicit():
    assert isinstance(metadata.tables["playhub_matches"].c.is_draw.type, Boolean)
    assert isinstance(metadata.tables["playhub_events"].c.start_datetime.type, DateTime)
    assert metadata.tables["playhub_events"].c.start_datetime.type.timezone is True
    assert isinstance(metadata.tables["rating_current"].c.rating.type, Float)
    assert str(metadata.tables["rating_history"].c.result.type) == "TEXT"


def test_rating_publication_keeps_previous_run_pointer():
    table = metadata.tables["rating_publications"]
    assert "previous_rating_run_id" in table.c
    assert table.c.previous_rating_run_id.nullable is True

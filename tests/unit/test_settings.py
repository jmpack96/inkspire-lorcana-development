from pathlib import Path

import pytest

from lorcana.config import ConfigurationError, Settings, sqlalchemy_postgres_url


def test_settings_do_not_require_database_at_import_time(tmp_path):
    settings = Settings.from_env({"LORCANA_DATA_DIR": str(tmp_path)})
    assert settings.database_url is None
    assert settings.data_dir == tmp_path
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        settings.require_database_url()


def test_postgres_url_validation_and_driver_normalization(tmp_path):
    settings = Settings.from_env({
        "DATABASE_URL": "postgresql://user:secret@localhost:5432/lorcana",
        "LORCANA_DATA_DIR": str(tmp_path),
    })
    assert settings.sqlalchemy_database_url().startswith("postgresql+psycopg://")
    assert "secret" not in repr(settings)
    assert sqlalchemy_postgres_url("postgres://host/db") == "postgresql+psycopg://host/db"


@pytest.mark.parametrize("value", ["", "sqlite:///tmp/x.db", "postgresql://host", "postgresql://host:bad/db"])
def test_invalid_database_urls_do_not_echo_secrets(value):
    with pytest.raises(ConfigurationError) as caught:
        Settings.from_env({"DATABASE_URL": value})
    assert "secret" not in str(caught.value)


def test_data_dir_must_be_absolute():
    with pytest.raises(ConfigurationError, match="absolute"):
        Settings.from_env({"LORCANA_DATA_DIR": "relative/path"})


def test_discord_settings_are_optional_but_validated(tmp_path):
    settings = Settings.from_env({"LORCANA_DATA_DIR": str(tmp_path)})
    assert settings.discord_bot_token is None
    assert settings.discord_team_slug == "inkspire"
    assert settings.live_event_channel_id is None
    with pytest.raises(ConfigurationError, match="DISCORD_BOT_TOKEN"):
        settings.require_discord_bot_token()

    configured = Settings.from_env({
        "LORCANA_DATA_DIR": str(tmp_path),
        "DISCORD_BOT_TOKEN": "super-secret-token",
        "LORCANA_DISCORD_TEAM_SLUG": "Inkspire",
        "LORCANA_LIVE_EVENT_CHANNEL_ID": "123456789",
    })
    assert configured.require_discord_bot_token() == "super-secret-token"
    assert configured.discord_team_slug == "inkspire"
    assert configured.live_event_channel_id == 123456789
    assert "super-secret-token" not in repr(configured)


def test_empty_discord_settings_are_rejected():
    with pytest.raises(ConfigurationError, match="DISCORD_BOT_TOKEN"):
        Settings.from_env({"DISCORD_BOT_TOKEN": "   "})
    with pytest.raises(ConfigurationError, match="LORCANA_DISCORD_TEAM_SLUG"):
        Settings.from_env({"LORCANA_DISCORD_TEAM_SLUG": "   "})
    with pytest.raises(ConfigurationError, match="LORCANA_LIVE_EVENT_CHANNEL_ID"):
        Settings.from_env({"LORCANA_LIVE_EVENT_CHANNEL_ID": "not-an-id"})


def test_coach_analyzer_settings_are_optional_and_versioned(tmp_path):
    settings = Settings.from_env({"LORCANA_DATA_DIR": str(tmp_path)})
    assert settings.coach_analyzer_name is None
    assert settings.coach_analyzer_generation == "v1"

    configured = Settings.from_env({
        "LORCANA_DATA_DIR": str(tmp_path),
        "LORCANA_COACH_ANALYZER": " Primary ",
        "LORCANA_COACH_ANALYZER_GENERATION": "prompt-2026-09",
    })
    assert configured.coach_analyzer_name == "primary"
    assert configured.coach_analyzer_generation == "prompt-2026-09"

    with pytest.raises(ConfigurationError, match="LORCANA_COACH_ANALYZER"):
        Settings.from_env({"LORCANA_COACH_ANALYZER": "   "})
    with pytest.raises(ConfigurationError, match="LORCANA_COACH_ANALYZER_GENERATION"):
        Settings.from_env({"LORCANA_COACH_ANALYZER_GENERATION": "   "})


def test_openai_coach_settings_are_secret_safe_and_generation_tracks_model(tmp_path):
    settings = Settings.from_env({
        "LORCANA_DATA_DIR": str(tmp_path),
        "LORCANA_COACH_ANALYZER": "openai",
        "OPENAI_API_KEY": "sk-super-secret",
        "OPENAI_COACH_MODEL": "gpt-custom",
    })
    assert settings.openai_api_key == "sk-super-secret"
    assert settings.openai_coach_model == "gpt-custom"
    assert settings.coach_analyzer_generation == "gpt-custom:lorcana_coach_v4_tournament_references"
    assert "sk-super-secret" not in repr(settings)

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        Settings.from_env({"OPENAI_API_KEY": "   "})
    with pytest.raises(ConfigurationError, match="OPENAI_COACH_MODEL"):
        Settings.from_env({"OPENAI_COACH_MODEL": "   "})

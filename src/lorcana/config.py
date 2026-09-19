"""Runtime configuration with no import-time I/O or connections."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit


class ConfigurationError(ValueError):
    """Configuration is absent or invalid; messages must not expose secrets."""


def _validated_postgres_url(value: str | None, *, name: str) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ConfigurationError(f"{name} must not be empty")
    try:
        parsed = urlsplit(value)
        valid_scheme = parsed.scheme in {"postgres", "postgresql", "postgresql+psycopg"}
        valid = valid_scheme and bool(parsed.hostname) and bool(parsed.path.strip("/"))
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError(f"{name} must be a PostgreSQL URL with a host and database")
    return value


def sqlalchemy_postgres_url(value: str) -> str:
    """Return a SQLAlchemy URL that explicitly selects psycopg 3."""
    parsed = urlsplit(value)
    return urlunsplit(("postgresql+psycopg", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


@dataclass(frozen=True)
class Settings:
    database_url: str | None = field(default=None, repr=False)
    environment: str = "development"
    data_dir: Path = field(default_factory=lambda: Path.cwd() / "data")
    discord_bot_token: str | None = field(default=None, repr=False)
    discord_team_slug: str = "inkspire"
    coach_analyzer_name: str | None = None
    coach_analyzer_generation: str = "v1"
    coach_rules_bundle: Path | None = None
    openai_api_key: str | None = field(default=None, repr=False)
    openai_coach_model: str = "gpt-5.6-terra"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        database_url = _validated_postgres_url(source.get("DATABASE_URL"), name="DATABASE_URL")
        environment = source.get("LORCANA_ENV", "development").strip().lower()
        if not environment:
            raise ConfigurationError("LORCANA_ENV must not be empty")
        raw_data_dir = source.get("LORCANA_DATA_DIR")
        if raw_data_dir is None:
            data_dir = Path.cwd() / "data"
        else:
            if not raw_data_dir.strip():
                raise ConfigurationError("LORCANA_DATA_DIR must not be empty")
            data_dir = Path(raw_data_dir).expanduser()
            if not data_dir.is_absolute():
                raise ConfigurationError("LORCANA_DATA_DIR must be an absolute path")
        discord_bot_token = source.get("DISCORD_BOT_TOKEN")
        if discord_bot_token is not None and not discord_bot_token.strip():
            raise ConfigurationError("DISCORD_BOT_TOKEN must not be empty")
        discord_team_slug = source.get("LORCANA_DISCORD_TEAM_SLUG", "inkspire").strip().lower()
        if not discord_team_slug:
            raise ConfigurationError("LORCANA_DISCORD_TEAM_SLUG must not be empty")
        raw_coach_name = source.get("LORCANA_COACH_ANALYZER")
        coach_analyzer_name = None if raw_coach_name is None else raw_coach_name.strip().lower()
        if raw_coach_name is not None and not coach_analyzer_name:
            raise ConfigurationError("LORCANA_COACH_ANALYZER must not be empty")
        openai_api_key = source.get("OPENAI_API_KEY")
        if openai_api_key is not None and not openai_api_key.strip():
            raise ConfigurationError("OPENAI_API_KEY must not be empty")
        openai_coach_model = source.get("OPENAI_COACH_MODEL", "gpt-5.6-terra").strip()
        if not openai_coach_model:
            raise ConfigurationError("OPENAI_COACH_MODEL must not be empty")
        default_generation = (
            f"{openai_coach_model}:lorcana_coach_v2_grounded"
            if coach_analyzer_name == "openai" else "v1"
        )
        coach_analyzer_generation = source.get(
            "LORCANA_COACH_ANALYZER_GENERATION", default_generation
        ).strip()
        if not coach_analyzer_generation:
            raise ConfigurationError("LORCANA_COACH_ANALYZER_GENERATION must not be empty")
        return cls(
            database_url=database_url,
            environment=environment,
            data_dir=data_dir,
            discord_bot_token=discord_bot_token,
            discord_team_slug=discord_team_slug,
            coach_analyzer_name=coach_analyzer_name,
            coach_analyzer_generation=coach_analyzer_generation,
            coach_rules_bundle=Path(source["LORCANA_COACH_RULES_BUNDLE"]) if source.get("LORCANA_COACH_RULES_BUNDLE") else None,
            openai_api_key=openai_api_key,
            openai_coach_model=openai_coach_model,
        )

    def require_database_url(self) -> str:
        if self.database_url is None:
            raise ConfigurationError("DATABASE_URL is required for PostgreSQL operations")
        return self.database_url

    def sqlalchemy_database_url(self) -> str:
        return sqlalchemy_postgres_url(self.require_database_url())

    def require_discord_bot_token(self) -> str:
        if self.discord_bot_token is None:
            raise ConfigurationError("DISCORD_BOT_TOKEN is required to run the Discord bot")
        return self.discord_bot_token

"""Operational analytics tables."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    Table,
    Text,
)

from lorcana.db.metadata import metadata


discord_command_usage = Table(
    "discord_command_usage",
    metadata,
    Column("usage_id", BigInteger, primary_key=True, autoincrement=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("command_name", Text, nullable=False),
    Column("invocation_mode", Text, nullable=False),
    Column("discord_user_id", BigInteger, nullable=False),
    Column("guild_id", BigInteger),
    Column("succeeded", Boolean, nullable=False),
    Column("duration_ms", Integer, nullable=False),
    CheckConstraint("duration_ms >= 0", name="discord_command_usage_duration_nonnegative"),
    Index("ix_discord_command_usage_occurred_at", "occurred_at"),
    Index(
        "ix_discord_command_usage_command_occurred",
        "command_name",
        "occurred_at",
    ),
)

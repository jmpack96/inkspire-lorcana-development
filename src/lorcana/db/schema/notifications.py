"""Durable outbound notification tables."""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from lorcana.db.metadata import metadata


discord_live_event_announcements = Table(
    "discord_live_event_announcements",
    metadata,
    Column("announcement_id", BigInteger, primary_key=True, autoincrement=True),
    Column("event_id", BigInteger, ForeignKey("playhub_events.event_id"), nullable=False),
    Column("channel_id", BigInteger, nullable=False),
    Column("event_url", Text, nullable=False),
    Column("message_content", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("sent_at", DateTime(timezone=True)),
    Column("discord_message_id", BigInteger),
    Column("last_error", Text),
    UniqueConstraint("event_id", "channel_id", name="uq_live_event_announcement_event_channel"),
    Index("ix_live_event_announcements_delivery", "status", "next_attempt_at"),
)

# One immutable report per team/channel/week; progress survives bot restarts.
from sqlalchemy.dialects.postgresql import JSONB

discord_weekly_duels_posts = Table(
    "discord_weekly_duels_posts", metadata,
    Column("team_slug", Text, primary_key=True),
    Column("channel_id", BigInteger, primary_key=True),
    Column("period_end", DateTime(timezone=True), primary_key=True),
    Column("pages", JSONB, nullable=False),
    Column("next_page", Integer, nullable=False, server_default="0"),
    Column("lease_until", DateTime(timezone=True)),
    Column("sent_at", DateTime(timezone=True)),
)

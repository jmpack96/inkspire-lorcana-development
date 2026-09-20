"""Durable Discord live-event announcements

Revision ID: 20260920_0009
Revises: 20260920_0008
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260920_0009"
down_revision: Union[str, Sequence[str], None] = "20260920_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_live_event_announcements",
        sa.Column("announcement_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("event_url", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("discord_message_id", sa.BigInteger()),
        sa.Column("last_error", sa.Text()),
        sa.ForeignKeyConstraint(["event_id"], ["playhub_events.event_id"]),
        sa.PrimaryKeyConstraint("announcement_id"),
        sa.UniqueConstraint(
            "event_id",
            "channel_id",
            name="uq_live_event_announcement_event_channel",
        ),
    )
    op.create_index(
        "ix_live_event_announcements_delivery",
        "discord_live_event_announcements",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_live_event_announcements_delivery",
        table_name="discord_live_event_announcements",
    )
    op.drop_table("discord_live_event_announcements")

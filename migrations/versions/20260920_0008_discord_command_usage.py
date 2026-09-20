"""Discord command usage analytics

Revision ID: 20260920_0008
Revises: 20260913_0007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260920_0008"
down_revision: Union[str, Sequence[str], None] = "20260913_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_command_usage",
        sa.Column("usage_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("command_name", sa.Text(), nullable=False),
        sa.Column("invocation_mode", sa.Text(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("guild_id", sa.BigInteger()),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="discord_command_usage_duration_nonnegative",
        ),
        sa.PrimaryKeyConstraint("usage_id"),
    )
    op.create_index(
        "ix_discord_command_usage_occurred_at",
        "discord_command_usage",
        ["occurred_at"],
    )
    op.create_index(
        "ix_discord_command_usage_command_occurred",
        "discord_command_usage",
        ["command_name", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discord_command_usage_command_occurred",
        table_name="discord_command_usage",
    )
    op.drop_index(
        "ix_discord_command_usage_occurred_at",
        table_name="discord_command_usage",
    )
    op.drop_table("discord_command_usage")

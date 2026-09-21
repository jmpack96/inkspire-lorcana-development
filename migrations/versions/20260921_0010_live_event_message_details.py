"""Include event and player details in live-event announcements

Revision ID: 20260921_0010
Revises: 20260920_0009
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260921_0010"
down_revision: Union[str, Sequence[str], None] = "20260920_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discord_live_event_announcements",
        sa.Column("message_content", sa.Text(), nullable=True),
    )
    op.execute(
        "UPDATE discord_live_event_announcements "
        "SET message_content = event_url "
        "WHERE message_content IS NULL"
    )
    op.alter_column(
        "discord_live_event_announcements",
        "message_content",
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("discord_live_event_announcements", "message_content")

"""Durable weekly Duels delivery progress."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261004_0011"
down_revision = "20260921_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("discord_weekly_duels_posts",
        sa.Column("team_slug", sa.Text(), primary_key=True),
        sa.Column("channel_id", sa.BigInteger(), primary_key=True),
        sa.Column("period_end", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("pages", JSONB(), nullable=False),
        sa.Column("next_page", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_table("discord_weekly_duels_posts")

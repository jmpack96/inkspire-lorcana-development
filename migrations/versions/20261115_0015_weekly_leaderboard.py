"""Track weekly Discord leaderboard delivery."""

from alembic import op
import sqlalchemy as sa

revision = "20261115_0015"
down_revision = "20261114_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discord_weekly_leaderboard_posts",
        sa.Column("team_slug", sa.Text(), primary_key=True),
        sa.Column("channel_id", sa.BigInteger(), primary_key=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("discord_weekly_leaderboard_posts")

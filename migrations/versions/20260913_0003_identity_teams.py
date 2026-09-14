"""identity and teams

Revision ID: 20260913_0003
Revises: 20260913_0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260913_0003"
down_revision: Union[str, Sequence[str], None] = "20260913_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "members",
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("preferred_display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','inactive')", name="members_status"),
        sa.PrimaryKeyConstraint("member_id"),
    )
    op.create_index("ix_members_preferred_display_name", "members", ["preferred_display_name"])

    op.create_table(
        "teams",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','inactive')", name="teams_status"),
        sa.PrimaryKeyConstraint("team_id"),
        sa.UniqueConstraint("slug", name="uq_teams_slug"),
    )

    op.create_table(
        "team_memberships",
        sa.Column("team_membership_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.team_id"]),
        sa.ForeignKeyConstraint(["member_id"], ["members.member_id"]),
        sa.PrimaryKeyConstraint("team_membership_id"),
    )
    op.create_index("ix_team_memberships_team_id", "team_memberships", ["team_id"])
    op.create_index("ix_team_memberships_member_id", "team_memberships", ["member_id"])
    op.create_index(
        "uq_team_memberships_active_member",
        "team_memberships",
        ["team_id", "member_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "member_playhub_links",
        sa.Column("player_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_by", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["member_id"], ["members.member_id"]),
        sa.PrimaryKeyConstraint("player_id"),
    )
    op.create_index("ix_member_playhub_links_member_id", "member_playhub_links", ["member_id"])
    op.create_index(
        "uq_member_playhub_links_primary_member",
        "member_playhub_links",
        ["member_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "discord_accounts",
        sa.Column("discord_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["members.member_id"]),
        sa.PrimaryKeyConstraint("discord_user_id"),
    )
    op.create_index("ix_discord_accounts_member_id", "discord_accounts", ["member_id"])


def downgrade() -> None:
    op.drop_index("ix_discord_accounts_member_id", table_name="discord_accounts")
    op.drop_table("discord_accounts")
    op.drop_index("uq_member_playhub_links_primary_member", table_name="member_playhub_links")
    op.drop_index("ix_member_playhub_links_member_id", table_name="member_playhub_links")
    op.drop_table("member_playhub_links")
    op.drop_index("uq_team_memberships_active_member", table_name="team_memberships")
    op.drop_index("ix_team_memberships_member_id", table_name="team_memberships")
    op.drop_index("ix_team_memberships_team_id", table_name="team_memberships")
    op.drop_table("team_memberships")
    op.drop_table("teams")
    op.drop_index("ix_members_preferred_display_name", table_name="members")
    op.drop_table("members")

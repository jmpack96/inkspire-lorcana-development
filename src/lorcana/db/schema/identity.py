"""Internal identity, account-link, and team tables."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Table,
    Text,
    Uuid,
    text,
)

from lorcana.db.metadata import metadata

members = Table(
    "members",
    metadata,
    Column("member_id", Uuid, primary_key=True),
    Column("preferred_display_name", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('active','inactive')", name="members_status"),
    Index("ix_members_preferred_display_name", "preferred_display_name"),
)

teams = Table(
    "teams",
    metadata,
    Column("team_id", Uuid, primary_key=True),
    Column("slug", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('active','inactive')", name="teams_status"),
)

team_memberships = Table(
    "team_memberships",
    metadata,
    Column("team_membership_id", Uuid, primary_key=True),
    Column("team_id", Uuid, ForeignKey("teams.team_id"), nullable=False),
    Column("member_id", Uuid, ForeignKey("members.member_id"), nullable=False),
    Column("role", Text, nullable=False),
    Column("joined_at", DateTime(timezone=True), nullable=False),
    Column("ended_at", DateTime(timezone=True)),
    Index("ix_team_memberships_team_id", "team_id"),
    Index("ix_team_memberships_member_id", "member_id"),
)
Index(
    "uq_team_memberships_active_member",
    team_memberships.c.team_id,
    team_memberships.c.member_id,
    unique=True,
    postgresql_where=text("ended_at IS NULL"),
)

member_playhub_links = Table(
    "member_playhub_links",
    metadata,
    # Provider identifiers may be linked before that player has appeared in our
    # ingested source corpus, so this is deliberately not a source-table FK.
    Column("player_id", BigInteger, primary_key=True, autoincrement=False),
    Column("member_id", Uuid, ForeignKey("members.member_id"), nullable=False),
    Column("is_primary", Boolean, nullable=False, server_default="true"),
    Column("linked_at", DateTime(timezone=True), nullable=False),
    Column("linked_by", Text),
    Index("ix_member_playhub_links_member_id", "member_id"),
)
Index(
    "uq_member_playhub_links_primary_member",
    member_playhub_links.c.member_id,
    unique=True,
    postgresql_where=text("is_primary"),
)

discord_accounts = Table(
    "discord_accounts",
    metadata,
    Column("discord_user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("member_id", Uuid, ForeignKey("members.member_id"), nullable=False),
    Column("linked_at", DateTime(timezone=True), nullable=False),
    Index("ix_discord_accounts_member_id", "member_id"),
)

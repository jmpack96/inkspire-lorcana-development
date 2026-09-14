"""SQL persistence for internal members and teams."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.dialects.postgresql import insert

from lorcana.db.schema.identity import (
    discord_accounts,
    member_playhub_links,
    members,
    team_memberships,
    teams,
)
from lorcana.teams.types import TeamMemberLink


class TeamRepository:
    def upsert_team(
        self,
        connection: Connection,
        *,
        team_id: UUID,
        slug: str,
        name: str,
        now: datetime,
    ) -> UUID:
        statement = insert(teams).values(
            team_id=team_id,
            slug=slug,
            name=name,
            status="active",
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[teams.c.slug],
            set_={"name": statement.excluded.name, "status": "active", "updated_at": now},
        ).returning(teams.c.team_id)
        return connection.execute(statement).scalar_one()

    def member_id_for_playhub_player(self, connection: Connection, player_id: int) -> UUID | None:
        return connection.execute(
            select(member_playhub_links.c.member_id).where(member_playhub_links.c.player_id == player_id)
        ).scalar_one_or_none()

    def create_member(
        self,
        connection: Connection,
        *,
        member_id: UUID,
        preferred_display_name: str,
        now: datetime,
    ) -> None:
        connection.execute(
            members.insert().values(
                member_id=member_id,
                preferred_display_name=preferred_display_name,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

    def update_member_name(
        self,
        connection: Connection,
        *,
        member_id: UUID,
        preferred_display_name: str,
        now: datetime,
    ) -> None:
        connection.execute(
            update(members)
            .where(members.c.member_id == member_id)
            .values(preferred_display_name=preferred_display_name, updated_at=now)
        )

    def link_playhub_player(
        self,
        connection: Connection,
        *,
        member_id: UUID,
        player_id: int,
        now: datetime,
        linked_by: str | None,
    ) -> None:
        # Never silently reassign a provider identity to a different internal member.
        existing = self.member_id_for_playhub_player(connection, player_id)
        if existing is not None and existing != member_id:
            raise ValueError(f"Play Hub player {player_id} is already linked to member {existing}")
        if existing == member_id:
            return
        has_primary = connection.execute(
            select(member_playhub_links.c.player_id)
            .where(member_playhub_links.c.member_id == member_id)
            .where(member_playhub_links.c.is_primary.is_(True))
            .limit(1)
        ).scalar_one_or_none()
        connection.execute(
            member_playhub_links.insert().values(
                player_id=player_id,
                member_id=member_id,
                is_primary=has_primary is None,
                linked_at=now,
                linked_by=linked_by,
            )
        )

    def ensure_active_membership(
        self,
        connection: Connection,
        *,
        membership_id: UUID,
        team_id: UUID,
        member_id: UUID,
        role: str,
        now: datetime,
    ) -> bool:
        existing = connection.execute(
            select(team_memberships.c.team_membership_id)
            .where(team_memberships.c.team_id == team_id)
            .where(team_memberships.c.member_id == member_id)
            .where(team_memberships.c.ended_at.is_(None))
        ).scalar_one_or_none()
        if existing is not None:
            connection.execute(
                update(team_memberships)
                .where(team_memberships.c.team_membership_id == existing)
                .values(role=role)
            )
            return False
        connection.execute(
            team_memberships.insert().values(
                team_membership_id=membership_id,
                team_id=team_id,
                member_id=member_id,
                role=role,
                joined_at=now,
            )
        )
        return True

    def active_members(self, connection: Connection, slug: str) -> list[TeamMemberLink]:
        statement = (
            select(
                members.c.member_id,
                members.c.preferred_display_name,
                member_playhub_links.c.player_id.label("playhub_player_id"),
                team_memberships.c.role,
            )
            .select_from(
                teams.join(team_memberships, team_memberships.c.team_id == teams.c.team_id)
                .join(members, members.c.member_id == team_memberships.c.member_id)
                .outerjoin(
                    member_playhub_links,
                    and_(
                        member_playhub_links.c.member_id == members.c.member_id,
                        member_playhub_links.c.is_primary.is_(True),
                    ),
                )
            )
            .where(teams.c.slug == slug)
            .where(teams.c.status == "active")
            .where(members.c.status == "active")
            .where(team_memberships.c.ended_at.is_(None))
            .order_by(members.c.preferred_display_name, members.c.member_id)
        )
        return [TeamMemberLink(**dict(row)) for row in connection.execute(statement).mappings()]

    def team_identity(self, connection: Connection, slug: str):
        return connection.execute(
            select(teams.c.team_id, teams.c.slug, teams.c.name)
            .where(teams.c.slug == slug)
            .where(teams.c.status == "active")
        ).mappings().one_or_none()

    def link_discord_account(
        self,
        connection: Connection,
        *,
        discord_user_id: int,
        member_id: UUID,
        linked_at: datetime,
    ) -> None:
        statement = insert(discord_accounts).values(
            discord_user_id=discord_user_id,
            member_id=member_id,
            linked_at=linked_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[discord_accounts.c.discord_user_id],
            set_={"member_id": member_id, "linked_at": linked_at},
        )
        connection.execute(statement)

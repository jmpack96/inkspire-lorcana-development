"""PostgreSQL persistence for internal member/provider identities."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from lorcana.db.schema.identity import (
    discord_accounts,
    member_playhub_links,
    members,
)


class IdentityRepository:
    def member_for_discord_user(self, connection: Connection, discord_user_id: int):
        return connection.execute(
            select(members.c.member_id, members.c.preferred_display_name)
            .select_from(
                discord_accounts.join(
                    members,
                    members.c.member_id == discord_accounts.c.member_id,
                )
            )
            .where(
                discord_accounts.c.discord_user_id == discord_user_id,
                members.c.status == "active",
            )
        ).mappings().one_or_none()

    def member_for_playhub_player(self, connection: Connection, player_id: int):
        return connection.execute(
            select(members.c.member_id, members.c.preferred_display_name)
            .select_from(
                member_playhub_links.join(
                    members,
                    members.c.member_id == member_playhub_links.c.member_id,
                )
            )
            .where(
                member_playhub_links.c.player_id == player_id,
                members.c.status == "active",
            )
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

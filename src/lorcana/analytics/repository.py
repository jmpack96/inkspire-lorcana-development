"""Persistence for Discord command usage analytics."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, distinct, func, insert, select
from sqlalchemy.engine import Connection

from lorcana.db.schema.analytics import discord_command_usage


class DiscordUsageRepository:
    def record(
        self,
        connection: Connection,
        *,
        occurred_at: datetime,
        command_name: str,
        invocation_mode: str,
        discord_user_id: int,
        guild_id: int | None,
        succeeded: bool,
        duration_ms: int,
    ) -> None:
        connection.execute(
            insert(discord_command_usage).values(
                occurred_at=occurred_at,
                command_name=command_name,
                invocation_mode=invocation_mode,
                discord_user_id=discord_user_id,
                guild_id=guild_id,
                succeeded=succeeded,
                duration_ms=duration_ms,
            )
        )

    def summary_rows(self, connection: Connection, *, start_at: datetime):
        return connection.execute(
            select(
                discord_command_usage.c.command_name,
                func.count().label("invocations"),
                func.count(distinct(discord_command_usage.c.discord_user_id)).label(
                    "unique_users"
                ),
                func.sum(
                    case((discord_command_usage.c.succeeded.is_(False), 1), else_=0)
                ).label("failures"),
                func.avg(discord_command_usage.c.duration_ms).label("average_duration_ms"),
                func.sum(
                    case(
                        (discord_command_usage.c.invocation_mode == "team_selector", 1),
                        else_=0,
                    )
                ).label("team_selector_invocations"),
            )
            .where(discord_command_usage.c.occurred_at >= start_at)
            .group_by(discord_command_usage.c.command_name)
            .order_by(discord_command_usage.c.command_name)
        ).mappings().all()

    def overall(self, connection: Connection, *, start_at: datetime):
        return connection.execute(
            select(
                func.count().label("invocations"),
                func.count(distinct(discord_command_usage.c.discord_user_id)).label(
                    "unique_users"
                ),
                func.sum(
                    case((discord_command_usage.c.succeeded.is_(False), 1), else_=0)
                ).label("failures"),
            ).where(discord_command_usage.c.occurred_at >= start_at)
        ).mappings().one()

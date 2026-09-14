"""Administrative workflows for explicit provider identity links."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import ContextManager
from uuid import UUID

from sqlalchemy.engine import Connection, Engine

from lorcana.db.tx import transaction
from lorcana.identity.repository import IdentityRepository
from lorcana.identity.types import MemberIdentity

Clock = Callable[[], datetime]
ReadConnectionFactory = Callable[[], ContextManager[Connection]]
TransactionFactory = Callable[[], ContextManager[Connection]]


class IdentityAdminError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IdentityAdminService:
    def __init__(
        self,
        *,
        repository: IdentityRepository,
        read_connection_factory: ReadConnectionFactory,
        transaction_factory: TransactionFactory,
        clock: Clock = utc_now,
    ) -> None:
        self.repository = repository
        self.read_connection_factory = read_connection_factory
        self.transaction_factory = transaction_factory
        self.clock = clock

    @classmethod
    def from_engine(cls, engine: Engine, **kwargs) -> "IdentityAdminService":
        @contextmanager
        def reader():
            with engine.connect() as connection:
                yield connection

        return cls(
            repository=IdentityRepository(),
            read_connection_factory=reader,
            transaction_factory=lambda: transaction(engine),
            **kwargs,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("IdentityAdminService clock must return timezone-aware datetimes")
        return value.astimezone(timezone.utc)

    def member_for_playhub_player(self, player_id: int) -> MemberIdentity:
        player_id = int(player_id)
        if player_id <= 0:
            raise ValueError("Play Hub player ID must be positive")
        with self.read_connection_factory() as connection:
            row = self.repository.member_for_playhub_player(connection, player_id)
        if row is None:
            raise IdentityAdminError(
                f"No active member is linked to Play Hub player ID {player_id}"
            )
        return MemberIdentity(**dict(row))

    def link_discord_for_playhub_player(
        self,
        *,
        player_id: int,
        discord_user_id: int,
    ) -> MemberIdentity:
        player_id = int(player_id)
        discord_user_id = int(discord_user_id)
        if player_id <= 0:
            raise ValueError("Play Hub player ID must be positive")
        if discord_user_id <= 0:
            raise ValueError("Discord user ID must be positive")
        now = self._now()
        with self.transaction_factory() as connection:
            row = self.repository.member_for_playhub_player(connection, player_id)
            if row is None:
                raise IdentityAdminError(
                    f"No active member is linked to Play Hub player ID {player_id}"
                )
            self.repository.link_discord_account(
                connection,
                discord_user_id=discord_user_id,
                member_id=row["member_id"],
                linked_at=now,
            )
        return MemberIdentity(**dict(row))

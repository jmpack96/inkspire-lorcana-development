"""Identity read service used by gateways such as Discord."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from typing import ContextManager

from sqlalchemy.engine import Connection, Engine

from lorcana.identity.repository import IdentityRepository
from lorcana.identity.types import MemberIdentity

ReadConnectionFactory = Callable[[], ContextManager[Connection]]


class IdentityQueryService:
    def __init__(self, *, repository: IdentityRepository, read_connection_factory: ReadConnectionFactory) -> None:
        self.repository = repository
        self.read_connection_factory = read_connection_factory

    @classmethod
    def from_engine(cls, engine: Engine) -> "IdentityQueryService":
        @contextmanager
        def reader():
            with engine.connect() as connection:
                yield connection
        return cls(repository=IdentityRepository(), read_connection_factory=reader)

    def member_for_discord_user(self, discord_user_id: int) -> MemberIdentity | None:
        if int(discord_user_id) <= 0:
            return None
        with self.read_connection_factory() as connection:
            row = self.repository.member_for_discord_user(connection, int(discord_user_id))
        return None if row is None else MemberIdentity(**dict(row))

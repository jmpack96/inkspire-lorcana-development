"""Application workflows for team and identity administration."""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager
from sqlalchemy.engine import Connection
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.engine import Engine

from lorcana.db.tx import transaction
from lorcana.teams.repository import TeamRepository
from lorcana.teams.types import TeamBootstrap, TeamBootstrapMember, TeamBootstrapResult


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_team_bootstrap(path: Path) -> TeamBootstrap:
    data = json.loads(path.read_text(encoding="utf-8"))
    team = data.get("team") or {}
    slug = str(team.get("slug") or "").strip().lower()
    name = str(team.get("name") or "").strip()
    if not slug or not name:
        raise ValueError("Team bootstrap requires non-empty team.slug and team.name")
    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValueError("Team bootstrap requires a non-empty members list")
    parsed: list[TeamBootstrapMember] = []
    seen_ids: set[int] = set()
    for index, item in enumerate(raw_members):
        if not isinstance(item, dict):
            raise ValueError(f"members[{index}] must be an object")
        display = str(item.get("preferred_display_name") or "").strip()
        try:
            player_id = int(item["playhub_player_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"members[{index}].playhub_player_id must be an integer") from error
        role = str(item.get("role") or "member").strip()
        if not display or not role or player_id <= 0:
            raise ValueError(f"members[{index}] has invalid display name, role, or player ID")
        if player_id in seen_ids:
            raise ValueError(f"Duplicate Play Hub player ID {player_id} in bootstrap")
        seen_ids.add(player_id)
        parsed.append(TeamBootstrapMember(display, player_id, role))
    return TeamBootstrap(slug=slug, name=name, members=tuple(parsed))


class TeamAdminService:
    def __init__(
        self,
        *,
        repository: TeamRepository,
        transaction_factory: Callable[[], ContextManager[Connection]],
        clock: Callable[[], datetime] = _now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.clock = clock
        self.uuid_factory = uuid_factory

    @classmethod
    def from_engine(
        cls,
        engine: Engine,
        *,
        repository: TeamRepository | None = None,
        **kwargs,
    ) -> "TeamAdminService":
        return cls(
            repository=repository or TeamRepository(),
            transaction_factory=lambda: transaction(engine),
            **kwargs,
        )

    def bootstrap(self, definition: TeamBootstrap, *, linked_by: str = "bootstrap") -> TeamBootstrapResult:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Team timestamps must be timezone-aware")
        created_members = 0
        created_memberships = 0
        with self.transaction_factory() as connection:
            team_id = self.repository.upsert_team(
                connection,
                team_id=self.uuid_factory(),
                slug=definition.slug,
                name=definition.name,
                now=now,
            )
            for item in definition.members:
                member_id = self.repository.member_id_for_playhub_player(connection, item.playhub_player_id)
                if member_id is None:
                    member_id = self.uuid_factory()
                    self.repository.create_member(
                        connection,
                        member_id=member_id,
                        preferred_display_name=item.preferred_display_name,
                        now=now,
                    )
                    self.repository.link_playhub_player(
                        connection,
                        member_id=member_id,
                        player_id=item.playhub_player_id,
                        now=now,
                        linked_by=linked_by,
                    )
                    created_members += 1
                else:
                    self.repository.update_member_name(
                        connection,
                        member_id=member_id,
                        preferred_display_name=item.preferred_display_name,
                        now=now,
                    )
                if self.repository.ensure_active_membership(
                    connection,
                    membership_id=self.uuid_factory(),
                    team_id=team_id,
                    member_id=member_id,
                    role=item.role,
                    now=now,
                ):
                    created_memberships += 1
        return TeamBootstrapResult(
            team_id=team_id,
            members_processed=len(definition.members),
            members_created=created_members,
            memberships_created=created_memberships,
        )

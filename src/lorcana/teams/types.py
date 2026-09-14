"""Storage-independent identity/team records."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TeamBootstrapMember:
    preferred_display_name: str
    playhub_player_id: int
    role: str = "member"


@dataclass(frozen=True)
class TeamBootstrap:
    slug: str
    name: str
    members: tuple[TeamBootstrapMember, ...]


@dataclass(frozen=True)
class TeamBootstrapResult:
    team_id: UUID
    members_processed: int
    members_created: int
    memberships_created: int


@dataclass(frozen=True)
class TeamMemberLink:
    member_id: UUID
    preferred_display_name: str
    playhub_player_id: int | None
    role: str

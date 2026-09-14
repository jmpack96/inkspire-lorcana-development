from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MemberIdentity:
    member_id: UUID
    preferred_display_name: str

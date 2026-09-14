from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ReplayEvidenceRef:
    game_id: str
    replay_id: UUID
    normalization_id: UUID
    feature_set_id: UUID
    started_at: datetime | None
    opponent_display_name: str | None
    result: str | None

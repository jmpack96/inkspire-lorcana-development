"""Read-only Duels evidence selection queries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection

from lorcana.db.schema.duels import (
    duels_connections,
    duels_feature_sets,
    duels_game_observations,
    duels_games,
    duels_normalizations,
    duels_replays,
)


class DuelsQueryRepository:
    def latest_evidence_for_game(
        self,
        connection: Connection,
        *,
        member_id: UUID,
        game_id: str,
        parser_version: str,
        extractor_version: str,
    ):
        return connection.execute(
            select(
                duels_replays.c.game_id,
                duels_replays.c.replay_id,
                duels_normalizations.c.normalization_id,
                duels_feature_sets.c.feature_set_id,
                duels_games.c.started_at,
                duels_game_observations.c.opponent_display_name,
                duels_game_observations.c.result,
            )
            .select_from(
                duels_replays
                .join(duels_connections, duels_connections.c.connection_id == duels_replays.c.connection_id)
                .join(duels_games, duels_games.c.game_id == duels_replays.c.game_id)
                .join(
                    duels_game_observations,
                    (duels_game_observations.c.connection_id == duels_replays.c.connection_id)
                    & (duels_game_observations.c.game_id == duels_replays.c.game_id),
                )
                .join(duels_normalizations, duels_normalizations.c.replay_id == duels_replays.c.replay_id)
                .join(duels_feature_sets, duels_feature_sets.c.normalization_id == duels_normalizations.c.normalization_id)
            )
            .where(
                duels_connections.c.member_id == member_id,
                duels_replays.c.game_id == game_id,
                duels_replays.c.status == "valid",
                duels_normalizations.c.status == "valid",
                duels_normalizations.c.parser_version == parser_version,
                duels_feature_sets.c.extractor_version == extractor_version,
            )
            .order_by(
                duels_replays.c.fetched_at.desc(),
                duels_normalizations.c.created_at.desc(),
                duels_feature_sets.c.created_at.desc(),
            )
            .limit(1)
        ).mappings().one_or_none()

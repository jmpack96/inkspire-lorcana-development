"""PostgreSQL persistence for Duels history and replay evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import and_, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from lorcana.db.schema.duels import (
    duels_connections,
    duels_feature_sets,
    duels_game_observations,
    duels_games,
    duels_normalizations,
    duels_replays,
)
from lorcana.duels.types import ParsedHistoryGame


class DuelsRepository:
    def create_connection(
        self,
        connection: Connection,
        *,
        connection_id: UUID,
        member_id: UUID,
        credential_ref: str,
        label: str | None,
        provider_account_id: str | None,
        now: datetime,
    ) -> None:
        connection.execute(
            duels_connections.insert().values(
                connection_id=connection_id,
                member_id=member_id,
                provider_account_id=provider_account_id,
                label=label,
                credential_ref=credential_ref,
                status="active",
                sync_cursor=None,
                history_exhausted=False,
                created_at=now,
                updated_at=now,
            )
        )

    def get_connection(self, connection: Connection, connection_id: UUID, *, for_update: bool = False):
        statement = select(duels_connections).where(duels_connections.c.connection_id == connection_id)
        if for_update:
            statement = statement.with_for_update()
        return connection.execute(statement).mappings().one_or_none()

    def begin_sync(self, connection: Connection, connection_id: UUID, *, now: datetime) -> None:
        connection.execute(
            update(duels_connections)
            .where(duels_connections.c.connection_id == connection_id)
            .values(
                last_sync_started_at=now,
                last_error_category=None,
                last_error_summary=None,
                updated_at=now,
            )
        )

    def save_sync_checkpoint(
        self,
        connection: Connection,
        connection_id: UUID,
        *,
        cursor: str | None,
        history_exhausted: bool,
        now: datetime,
    ) -> None:
        connection.execute(
            update(duels_connections)
            .where(duels_connections.c.connection_id == connection_id)
            .values(
                sync_cursor=cursor,
                history_exhausted=history_exhausted,
                updated_at=now,
            )
        )

    def finish_sync(
        self,
        connection: Connection,
        connection_id: UUID,
        *,
        cursor: str | None,
        history_exhausted: bool,
        now: datetime,
    ) -> None:
        connection.execute(
            update(duels_connections)
            .where(duels_connections.c.connection_id == connection_id)
            .values(
                sync_cursor=cursor,
                history_exhausted=history_exhausted,
                last_sync_completed_at=now,
                last_error_category=None,
                last_error_summary=None,
                status="active",
                updated_at=now,
            )
        )

    def record_sync_error(
        self,
        connection: Connection,
        connection_id: UUID,
        *,
        category: str,
        summary: str,
        auth_error: bool,
        now: datetime,
    ) -> None:
        connection.execute(
            update(duels_connections)
            .where(duels_connections.c.connection_id == connection_id)
            .values(
                status="auth_error" if auth_error else "active",
                last_error_category=category[:100],
                last_error_summary=summary[:1000],
                updated_at=now,
            )
        )

    def upsert_history_game(
        self,
        connection: Connection,
        *,
        connection_id: UUID,
        game: ParsedHistoryGame,
        observed_at: datetime,
    ) -> bool:
        observation_existed = connection.execute(
            select(duels_game_observations.c.game_id).where(
                duels_game_observations.c.connection_id == connection_id,
                duels_game_observations.c.game_id == game.game_id,
            )
        ).scalar_one_or_none() is not None

        game_insert = insert(duels_games).values(
            game_id=game.game_id,
            match_id=game.match_id,
            match_format=game.match_format,
            match_game_number=game.match_game_number,
            mode=game.mode,
            queue_id=game.queue_id,
            queue_name=game.queue_name,
            ranked=game.ranked,
            season_id=game.season_id,
            season_name=game.season_name,
            started_at=game.started_at,
            ended_at=game.ended_at,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
        )
        connection.execute(
            game_insert.on_conflict_do_update(
                index_elements=[duels_games.c.game_id],
                set_={
                    "match_id": game_insert.excluded.match_id,
                    "match_format": game_insert.excluded.match_format,
                    "match_game_number": game_insert.excluded.match_game_number,
                    "mode": game_insert.excluded.mode,
                    "queue_id": game_insert.excluded.queue_id,
                    "queue_name": game_insert.excluded.queue_name,
                    "ranked": game_insert.excluded.ranked,
                    "season_id": game_insert.excluded.season_id,
                    "season_name": game_insert.excluded.season_name,
                    "started_at": game_insert.excluded.started_at,
                    "ended_at": game_insert.excluded.ended_at,
                    "last_seen_at": observed_at,
                },
            )
        )

        observation_insert = insert(duels_game_observations).values(
            connection_id=connection_id,
            game_id=game.game_id,
            result=game.result,
            went_first=game.went_first,
            your_deck_colors=game.your_deck_colors,
            opponent_display_name=game.opponent_display_name,
            opponent_deck_colors=game.opponent_deck_colors,
            provider_replay_id=game.provider_replay_id,
            replay_url=game.replay_url,
            provider_payload=game.provider_payload,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
        )
        connection.execute(
            observation_insert.on_conflict_do_update(
                index_elements=[
                    duels_game_observations.c.connection_id,
                    duels_game_observations.c.game_id,
                ],
                set_={
                    "result": observation_insert.excluded.result,
                    "went_first": observation_insert.excluded.went_first,
                    "your_deck_colors": observation_insert.excluded.your_deck_colors,
                    "opponent_display_name": observation_insert.excluded.opponent_display_name,
                    "opponent_deck_colors": observation_insert.excluded.opponent_deck_colors,
                    "provider_replay_id": observation_insert.excluded.provider_replay_id,
                    "replay_url": observation_insert.excluded.replay_url,
                    "provider_payload": observation_insert.excluded.provider_payload,
                    "last_seen_at": observed_at,
                },
            )
        )
        return not observation_existed

    def pending_replays(self, connection: Connection, connection_id: UUID, *, limit: int = 500):
        matching_replay = exists(
            select(1).where(
                duels_replays.c.connection_id == duels_game_observations.c.connection_id,
                duels_replays.c.game_id == duels_game_observations.c.game_id,
                duels_replays.c.provider_replay_id.is_not_distinct_from(
                    duels_game_observations.c.provider_replay_id
                ),
            )
        )
        return connection.execute(
            select(
                duels_game_observations.c.connection_id,
                duels_game_observations.c.game_id,
                duels_game_observations.c.provider_replay_id,
                duels_game_observations.c.replay_url,
            )
            .where(
                duels_game_observations.c.connection_id == connection_id,
                duels_game_observations.c.replay_url.is_not(None),
                ~matching_replay,
            )
            .order_by(duels_game_observations.c.last_seen_at.desc())
            .limit(limit)
        ).mappings().all()

    def get_observation(self, connection: Connection, connection_id: UUID, game_id: str):
        return connection.execute(
            select(duels_game_observations).where(
                duels_game_observations.c.connection_id == connection_id,
                duels_game_observations.c.game_id == game_id,
            )
        ).mappings().one_or_none()

    def latest_replay(self, connection: Connection, connection_id: UUID, game_id: str):
        return connection.execute(
            select(duels_replays)
            .where(
                duels_replays.c.connection_id == connection_id,
                duels_replays.c.game_id == game_id,
            )
            .order_by(duels_replays.c.fetched_at.desc(), duels_replays.c.replay_id.desc())
            .limit(1)
        ).mappings().one_or_none()

    def insert_replay(
        self,
        connection: Connection,
        *,
        replay_id: UUID,
        connection_id: UUID,
        game_id: str,
        provider_replay_id: str | None,
        perspective: int | None,
        fetched_at: datetime,
        source_sha256: str,
        content_encoding: str,
        source_bytes: bytes,
        status: str,
        validation: Mapping[str, Any] | None,
    ) -> tuple[UUID, bool]:
        statement = (
            insert(duels_replays)
            .values(
                replay_id=replay_id,
                connection_id=connection_id,
                game_id=game_id,
                provider_replay_id=provider_replay_id,
                perspective=perspective,
                fetched_at=fetched_at,
                source_sha256=source_sha256,
                content_encoding=content_encoding,
                compressed_bytes=source_bytes,
                compressed_size=len(source_bytes),
                status=status,
                validation=dict(validation) if validation is not None else None,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    duels_replays.c.connection_id,
                    duels_replays.c.game_id,
                    duels_replays.c.source_sha256,
                ]
            )
            .returning(duels_replays.c.replay_id)
        )
        created = connection.execute(statement).scalar_one_or_none()
        if created is not None:
            return created, True
        existing = connection.execute(
            select(duels_replays.c.replay_id).where(
                duels_replays.c.connection_id == connection_id,
                duels_replays.c.game_id == game_id,
                duels_replays.c.source_sha256 == source_sha256,
            )
        ).scalar_one()
        return existing, False

    def get_normalization(self, connection: Connection, replay_id: UUID, parser_version: str):
        return connection.execute(
            select(duels_normalizations).where(
                duels_normalizations.c.replay_id == replay_id,
                duels_normalizations.c.parser_version == parser_version,
            )
        ).mappings().one_or_none()

    def insert_normalization(
        self,
        connection: Connection,
        *,
        normalization_id: UUID,
        replay_id: UUID,
        parser_version: str,
        schema_version: int,
        normalized: Mapping[str, Any],
        normalized_sha256: str,
        warnings: list[Any],
        created_at: datetime,
    ) -> tuple[UUID, bool]:
        statement = (
            insert(duels_normalizations)
            .values(
                normalization_id=normalization_id,
                replay_id=replay_id,
                parser_version=parser_version,
                schema_version=schema_version,
                normalized=dict(normalized),
                normalized_sha256=normalized_sha256,
                warnings=warnings,
                status="valid",
                created_at=created_at,
            )
            .on_conflict_do_nothing(
                index_elements=[duels_normalizations.c.replay_id, duels_normalizations.c.parser_version]
            )
            .returning(duels_normalizations.c.normalization_id)
        )
        created = connection.execute(statement).scalar_one_or_none()
        if created is not None:
            return created, True
        existing = connection.execute(
            select(duels_normalizations.c.normalization_id).where(
                duels_normalizations.c.replay_id == replay_id,
                duels_normalizations.c.parser_version == parser_version,
            )
        ).scalar_one()
        return existing, False

    def get_feature_set(self, connection: Connection, normalization_id: UUID, extractor_version: str):
        return connection.execute(
            select(duels_feature_sets).where(
                duels_feature_sets.c.normalization_id == normalization_id,
                duels_feature_sets.c.extractor_version == extractor_version,
            )
        ).mappings().one_or_none()

    def insert_feature_set(
        self,
        connection: Connection,
        *,
        feature_set_id: UUID,
        normalization_id: UUID,
        extractor_version: str,
        features: Mapping[str, Any],
        features_sha256: str,
        created_at: datetime,
    ) -> tuple[UUID, bool]:
        statement = (
            insert(duels_feature_sets)
            .values(
                feature_set_id=feature_set_id,
                normalization_id=normalization_id,
                extractor_version=extractor_version,
                features=dict(features),
                features_sha256=features_sha256,
                created_at=created_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    duels_feature_sets.c.normalization_id,
                    duels_feature_sets.c.extractor_version,
                ]
            )
            .returning(duels_feature_sets.c.feature_set_id)
        )
        created = connection.execute(statement).scalar_one_or_none()
        if created is not None:
            return created, True
        existing = connection.execute(
            select(duels_feature_sets.c.feature_set_id).where(
                duels_feature_sets.c.normalization_id == normalization_id,
                duels_feature_sets.c.extractor_version == extractor_version,
            )
        ).scalar_one()
        return existing, False

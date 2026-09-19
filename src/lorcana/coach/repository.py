"""PostgreSQL persistence and access-controlled evidence lookup for Coach."""

from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any, Iterable, Mapping
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from lorcana.db.schema.catalog import catalog_cards, catalog_snapshots
from lorcana.db.schema.coach import coach_analysis_runs, coach_findings, coach_reports, decklist_cards, decklists
from lorcana.db.schema.duels import duels_connections, duels_feature_sets, duels_normalizations, duels_replays, duels_games


class CoachRepository:

    def lock_idempotency(self, connection: Connection, key: str) -> None:
        # Transaction-scoped PostgreSQL advisory lock. Identical Coach requests
        # serialize only through run creation/status lookup; the external model
        # call itself never runs while holding a database transaction open.
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        connection.execute(select(func.pg_advisory_xact_lock(lock_id))).scalar_one()

    def create_decklist(
        self,
        connection: Connection,
        *,
        decklist_id: UUID,
        member_id: UUID,
        catalog_snapshot_id: UUID | None,
        name: str | None,
        source: str,
        source_reference: str | None,
        notes: str | None,
        created_at: datetime,
        cards: Iterable[Mapping[str, Any]],
    ) -> None:
        connection.execute(
            decklists.insert().values(
                decklist_id=decklist_id,
                member_id=member_id,
                catalog_snapshot_id=catalog_snapshot_id,
                name=name,
                source=source,
                source_reference=source_reference,
                notes=notes,
                created_at=created_at,
            )
        )
        rows = [{**dict(card), "decklist_id": decklist_id} for card in cards]
        if rows:
            connection.execute(decklist_cards.insert(), rows)

    def evidence(self, connection: Connection, *, member_id: UUID, normalization_id: UUID, feature_set_id: UUID):
        statement = (
            select(
                duels_normalizations.c.normalization_id,
                duels_normalizations.c.normalized,
                duels_normalizations.c.parser_version,
                duels_normalizations.c.normalized_sha256,
                duels_feature_sets.c.feature_set_id,
                duels_feature_sets.c.features,
                duels_feature_sets.c.extractor_version,
                duels_feature_sets.c.features_sha256,
                duels_replays.c.replay_id,
                duels_replays.c.game_id,
                duels_games.c.started_at.label("played_at"),
            )
            .select_from(
                duels_normalizations
                .join(duels_replays, duels_replays.c.replay_id == duels_normalizations.c.replay_id)
                .join(duels_games, duels_games.c.game_id == duels_replays.c.game_id)
                .join(duels_connections, duels_connections.c.connection_id == duels_replays.c.connection_id)
                .join(
                    duels_feature_sets,
                    duels_feature_sets.c.normalization_id == duels_normalizations.c.normalization_id,
                )
            )
            .where(
                duels_connections.c.member_id == member_id,
                duels_normalizations.c.normalization_id == normalization_id,
                duels_feature_sets.c.feature_set_id == feature_set_id,
            )
        )
        return connection.execute(statement).mappings().one_or_none()

    def catalog_snapshot(self, connection: Connection, snapshot_id: UUID):
        return connection.execute(
            select(catalog_snapshots).where(catalog_snapshots.c.snapshot_id == snapshot_id)
        ).mappings().one_or_none()

    def catalog_facts(self, connection: Connection, snapshot_id: UUID, card_ids: Iterable[str]):
        ids = sorted(set(card_ids))
        if not ids:
            return []
        return connection.execute(
            select(catalog_cards).where(
                catalog_cards.c.snapshot_id == snapshot_id,
                catalog_cards.c.card_id.in_(ids),
            )
        ).mappings().all()

    def catalog_all_facts(self, connection: Connection, snapshot_id: UUID):
        return connection.execute(select(catalog_cards).where(
            catalog_cards.c.snapshot_id == snapshot_id
        )).mappings().all()

    def decklist(self, connection: Connection, member_id: UUID, decklist_id: UUID):
        deck = connection.execute(
            select(decklists).where(
                decklists.c.decklist_id == decklist_id,
                decklists.c.member_id == member_id,
            )
        ).mappings().one_or_none()
        if deck is None:
            return None
        cards = connection.execute(
            select(decklist_cards)
            .where(decklist_cards.c.decklist_id == decklist_id)
            .order_by(decklist_cards.c.card_name, decklist_cards.c.card_id)
        ).mappings().all()
        return deck, cards

    def run_by_idempotency(self, connection: Connection, key: str, *, for_update: bool = False):
        statement = select(coach_analysis_runs).where(coach_analysis_runs.c.idempotency_key == key)
        if for_update:
            statement = statement.with_for_update()
        return connection.execute(statement).mappings().one_or_none()

    def create_run(self, connection: Connection, **values: Any) -> bool:
        statement = (
            insert(coach_analysis_runs)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[coach_analysis_runs.c.idempotency_key])
            .returning(coach_analysis_runs.c.analysis_run_id)
        )
        return connection.execute(statement).scalar_one_or_none() is not None

    def restart_run(self, connection: Connection, analysis_run_id: UUID, *, started_at: datetime) -> None:
        connection.execute(
            update(coach_analysis_runs)
            .where(
                coach_analysis_runs.c.analysis_run_id == analysis_run_id,
                coach_analysis_runs.c.status.in_(["failed", "running"]),
            )
            .values(
                status="running",
                started_at=started_at,
                completed_at=None,
                error_category=None,
                error_summary=None,
                usage=None,
            )
        )
        connection.execute(delete(coach_findings).where(coach_findings.c.analysis_run_id == analysis_run_id))
        connection.execute(delete(coach_reports).where(coach_reports.c.analysis_run_id == analysis_run_id))

    def mark_failed(self, connection: Connection, analysis_run_id: UUID, *, completed_at: datetime, error: Exception) -> None:
        connection.execute(
            update(coach_analysis_runs)
            .where(coach_analysis_runs.c.analysis_run_id == analysis_run_id)
            .values(
                status="failed",
                completed_at=completed_at,
                error_category=type(error).__name__[:200],
                error_summary=str(error)[:4000],
            )
        )

    def complete(
        self,
        connection: Connection,
        *,
        analysis_run_id: UUID,
        findings: Iterable[Mapping[str, Any]],
        report_id: UUID,
        report_content: str,
        usage: Mapping[str, Any] | None,
        completed_at: datetime,
    ) -> None:
        finding_rows = list(findings)
        if finding_rows:
            connection.execute(coach_findings.insert(), finding_rows)
        connection.execute(
            coach_reports.insert().values(
                report_id=report_id,
                analysis_run_id=analysis_run_id,
                format="markdown",
                content=report_content,
                created_at=completed_at,
            )
        )
        connection.execute(
            update(coach_analysis_runs)
            .where(coach_analysis_runs.c.analysis_run_id == analysis_run_id)
            .values(status="succeeded", usage=dict(usage) if usage else None, completed_at=completed_at)
        )

    def report_for_run(self, connection: Connection, analysis_run_id: UUID, *, member_id: UUID | None = None):
        statement = (
            select(
                coach_reports.c.report_id,
                coach_reports.c.content,
                coach_analysis_runs.c.analysis_run_id,
                coach_analysis_runs.c.member_id,
                coach_analysis_runs.c.status,
            )
            .select_from(
                coach_reports.join(
                    coach_analysis_runs,
                    coach_analysis_runs.c.analysis_run_id == coach_reports.c.analysis_run_id,
                )
            )
            .where(coach_analysis_runs.c.analysis_run_id == analysis_run_id)
        )
        if member_id is not None:
            statement = statement.where(coach_analysis_runs.c.member_id == member_id)
        return connection.execute(statement).mappings().one_or_none()

    def finding_count(self, connection: Connection, analysis_run_id: UUID) -> int:
        value = connection.execute(
            select(func.count())
            .select_from(coach_findings)
            .where(coach_findings.c.analysis_run_id == analysis_run_id)
        ).scalar_one()
        return int(value)

    def latest_report_for_game(self, connection: Connection, *, member_id: UUID, game_id: str):
        return connection.execute(
            select(
                coach_reports.c.report_id,
                coach_reports.c.content,
                coach_analysis_runs.c.analysis_run_id,
                coach_analysis_runs.c.member_id,
                coach_analysis_runs.c.status,
            )
            .select_from(
                coach_reports
                .join(
                    coach_analysis_runs,
                    coach_analysis_runs.c.analysis_run_id == coach_reports.c.analysis_run_id,
                )
                .join(
                    duels_normalizations,
                    duels_normalizations.c.normalization_id == coach_analysis_runs.c.normalization_id,
                )
                .join(duels_replays, duels_replays.c.replay_id == duels_normalizations.c.replay_id)
            )
            .where(
                coach_analysis_runs.c.member_id == member_id,
                coach_analysis_runs.c.status == "succeeded",
                duels_replays.c.game_id == game_id,
            )
            .order_by(coach_analysis_runs.c.completed_at.desc(), coach_analysis_runs.c.analysis_run_id.desc())
            .limit(1)
        ).mappings().one_or_none()

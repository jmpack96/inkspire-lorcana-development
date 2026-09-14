"""Application workflow for requesting one replay analysis via the durable job queue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from lorcana.catalog.service import CatalogService
from lorcana.duels.query_service import DuelsQueryService
from lorcana.jobs.kinds import enqueue_coach_analysis
from lorcana.jobs.service import JobQueue


class CoachRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class CoachRequestResult:
    job_id: UUID
    created: bool
    game_id: str
    normalization_id: UUID
    feature_set_id: UUID
    catalog_snapshot_id: UUID


class CoachRequestService:
    def __init__(
        self,
        *,
        duels: DuelsQueryService,
        catalog: CatalogService,
        jobs: JobQueue,
        analyzer_name: str,
        analyzer_generation: str = "v1",
    ) -> None:
        self.duels = duels
        self.catalog = catalog
        self.jobs = jobs
        self.analyzer_name = analyzer_name.strip().lower()
        self.analyzer_generation = analyzer_generation.strip()
        if not self.analyzer_name:
            raise ValueError("analyzer_name must not be empty")
        if not self.analyzer_generation:
            raise ValueError("analyzer_generation must not be empty")

    def request(
        self,
        *,
        member_id: UUID,
        game_id: str,
        decklist_id: UUID | None = None,
        analysis_config: Mapping[str, Any] | None = None,
    ) -> CoachRequestResult:
        evidence = self.duels.latest_evidence_for_game(member_id, game_id)
        if evidence is None:
            raise CoachRequestError("No Coach-ready replay evidence was found for that game")
        catalog_snapshot_id = self.catalog.latest_snapshot_id()
        if catalog_snapshot_id is None:
            raise CoachRequestError("No card catalog snapshot is available")
        queued = enqueue_coach_analysis(
            self.jobs,
            member_id=member_id,
            normalization_id=evidence.normalization_id,
            feature_set_id=evidence.feature_set_id,
            catalog_snapshot_id=catalog_snapshot_id,
            analyzer_name=self.analyzer_name,
            analyzer_generation=self.analyzer_generation,
            decklist_id=decklist_id,
            analysis_config=dict(analysis_config or {}),
        )
        return CoachRequestResult(
            job_id=queued.job_id,
            created=queued.created,
            game_id=evidence.game_id,
            normalization_id=evidence.normalization_id,
            feature_set_id=evidence.feature_set_id,
            catalog_snapshot_id=catalog_snapshot_id,
        )

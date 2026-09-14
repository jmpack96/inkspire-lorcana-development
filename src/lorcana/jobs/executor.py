"""Concrete worker handlers for platform jobs."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Engine

from lorcana.catalog.lorcast import LorcastClient
from lorcana.catalog.service import CatalogService
from lorcana.coach.registry import AnalyzerNotConfiguredError, AnalyzerRegistry
from lorcana.coach.service import CoachService
from lorcana.duels.service import DuelsService
from lorcana.jobs.kinds import (
    DUELS_PROCESS_REPLAY,
    DUELS_SYNC_CONNECTION,
    COACH_ANALYZE_REPLAY,
    CATALOG_REFRESH_LORCAST,
    MAINTENANCE_PRUNE_JOBS,
    PLAYHUB_DISCOVER_DAY,
    PLAYHUB_DISCOVER_WINDOW,
    PLAYHUB_IMPORT_EVENT,
    PLAYHUB_IMPORT_SWEEP,
    RATINGS_BUILD_PUBLISH,
    enqueue_duels_replay,
    enqueue_duels_sync,
    enqueue_event_import,
)
from lorcana.jobs.service import JobQueue
from lorcana.jobs.types import JobLease
from lorcana.playhub.client import PlayHubClient
from lorcana.playhub.service import (
    PlayHubDiscoveryService,
    PlayHubImportService,
    PlayHubMaintenanceService,
)
from lorcana.ratings.policy import policy_from_name
from lorcana.ratings.service import RatingService


class PermanentJobError(RuntimeError):
    """A malformed/unsupported job should not be retried."""


class PlatformJobExecutor:
    def __init__(self, engine: Engine, *, analyzer_registry: AnalyzerRegistry | None = None) -> None:
        self.engine = engine
        self.queue = JobQueue.from_engine(engine)
        self.analyzer_registry = analyzer_registry or AnalyzerRegistry()

    def execute(self, lease: JobLease) -> dict[str, Any]:
        if lease.kind == PLAYHUB_DISCOVER_DAY:
            return self._discover_day(lease.payload)
        if lease.kind == PLAYHUB_IMPORT_EVENT:
            return self._import_event(lease.payload)
        if lease.kind == PLAYHUB_DISCOVER_WINDOW:
            return self._discover_window(lease.payload)
        if lease.kind == PLAYHUB_IMPORT_SWEEP:
            return self._enqueue_due_imports(lease.payload)
        if lease.kind == RATINGS_BUILD_PUBLISH:
            return self._build_ratings(lease.payload)
        if lease.kind == DUELS_SYNC_CONNECTION:
            return self._sync_duels_connection(lease.payload)
        if lease.kind == DUELS_PROCESS_REPLAY:
            return self._process_duels_replay(lease.payload)
        if lease.kind == CATALOG_REFRESH_LORCAST:
            return self._refresh_lorcast_catalog()
        if lease.kind == MAINTENANCE_PRUNE_JOBS:
            return self._prune_jobs(lease.payload)
        if lease.kind == COACH_ANALYZE_REPLAY:
            return self._coach_analyze_replay(
                lease.payload,
                restart_running=lease.attempt_number > 1,
            )
        raise PermanentJobError(f"Unsupported job kind: {lease.kind}")

    def _discover_day(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            day = date.fromisoformat(str(payload["day"]))
            force = bool(payload.get("force", False))
        except (KeyError, TypeError, ValueError) as error:
            raise PermanentJobError("playhub.discover_day requires an ISO day") from error
        client = PlayHubClient()
        try:
            result = PlayHubDiscoveryService.from_engine(self.engine, client=client).sync_day(
                day, force=force
            )
        finally:
            client.close()
        return {
            "day": day.isoformat(),
            "skipped": result.skipped,
            "events_received": result.events_received,
            "unique_events": result.unique_events,
            "persisted_events": result.persisted_events,
        }

    def _discover_window(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            start_day = date.fromisoformat(str(payload["start_date"]))
            lookahead_days = int(payload.get("lookahead_days", 180))
            chunk_days = int(payload.get("chunk_days", 7))
            force = bool(payload.get("force", True))
        except (KeyError, TypeError, ValueError) as error:
            raise PermanentJobError(
                "playhub.discover_window requires start_date and integer window settings"
            ) from error
        if not 0 <= lookahead_days <= 366:
            raise PermanentJobError("playhub.discover_window lookahead_days must be between 0 and 366")
        if not 1 <= chunk_days <= 31:
            raise PermanentJobError("playhub.discover_window chunk_days must be between 1 and 31")

        end_exclusive = start_day + timedelta(days=lookahead_days + 1)
        client = PlayHubClient()
        totals = {
            "windows": 0,
            "events_received": 0,
            "unique_events": 0,
            "persisted_events": 0,
            "skipped_windows": 0,
        }
        try:
            service = PlayHubDiscoveryService.from_engine(self.engine, client=client)
            cursor = start_day
            while cursor < end_exclusive:
                chunk_end = min(cursor + timedelta(days=chunk_days), end_exclusive)
                result = service.sync_range(cursor, chunk_end, force=force)
                totals["windows"] += 1
                totals["events_received"] += result.events_received
                totals["unique_events"] += result.unique_events
                totals["persisted_events"] += result.persisted_events
                totals["skipped_windows"] += int(result.skipped)
                cursor = chunk_end
        finally:
            client.close()
        return {
            "start_date": start_day.isoformat(),
            "end_date_exclusive": end_exclusive.isoformat(),
            **totals,
        }

    def _enqueue_due_imports(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            lookback_days = int(payload.get("lookback_days", 14))
            retry_minutes = int(payload.get("retry_minutes", 60))
            limit = int(payload.get("limit", 500))
        except (TypeError, ValueError) as error:
            raise PermanentJobError("playhub.import_sweep settings must be integers") from error
        generation = str(
            payload.get("generation")
            or datetime.now(timezone.utc).date().isoformat()
        ).strip()
        if not generation:
            raise PermanentJobError("playhub.import_sweep generation must not be empty")
        try:
            event_ids = PlayHubMaintenanceService.from_engine(self.engine).due_event_import_ids(
                lookback_days=lookback_days,
                retry_minutes=retry_minutes,
                limit=limit,
            )
        except ValueError as error:
            raise PermanentJobError(str(error)) from error
        created = 0
        for event_id in event_ids:
            queued = enqueue_event_import(
                self.queue,
                event_id,
                generation=f"sweep:{generation}",
            )
            created += int(queued.created)
        return {
            "candidate_events": len(event_ids),
            "import_jobs_created": created,
            "generation": generation,
        }

    def _import_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            event_id = int(payload["event_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise PermanentJobError("playhub.import_event requires event_id") from error
        client = PlayHubClient()
        try:
            result = PlayHubImportService.from_engine(self.engine, client=client).import_event(event_id)
        finally:
            client.close()
        return {
            "event_id": result.event_id,
            "status": result.status,
            "rounds_imported": result.rounds_imported,
            "rounds_expected": result.rounds_expected,
            "matches_found": result.matches_found,
        }

    def _build_ratings(self, payload: dict[str, Any]) -> dict[str, Any]:
        publication_name = str(payload.get("publication_name", "global_elo")).strip()
        policy_name = str(payload.get("policy", "global"))
        if not publication_name:
            raise PermanentJobError("ratings.build_publish requires publication_name")
        try:
            policy = policy_from_name(policy_name)
        except ValueError as error:
            raise PermanentJobError(str(error)) from error
        result = RatingService.from_engine(self.engine, policy=policy).build_and_publish_if_changed(
            publication_name=publication_name,
            published_by="lorcana-worker",
        )
        return {
            "rating_run_id": str(result.rating_run_id),
            "publication_name": publication_name,
            "input_count": result.input_count,
            "player_count": result.player_count,
            "ordered_input_digest": result.ordered_input_digest,
            "status": result.status,
        }

    def _prune_jobs(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            retention_days = int(payload.get("retention_days", 30))
            limit = int(payload.get("limit", 5_000))
        except (TypeError, ValueError) as error:
            raise PermanentJobError("maintenance.prune_jobs settings must be integers") from error
        if not 7 <= retention_days <= 3650:
            raise PermanentJobError("maintenance.prune_jobs retention_days must be between 7 and 3650")
        if not 1 <= limit <= 50_000:
            raise PermanentJobError("maintenance.prune_jobs limit must be between 1 and 50000")
        now = datetime.now(timezone.utc)
        with self.queue.transaction_factory() as connection:
            deleted = self.queue.repository.prune_completed_before(
                connection,
                completed_before=now - timedelta(days=retention_days),
                limit=limit,
            )
        return {
            "deleted_jobs": deleted,
            "retention_days": retention_days,
        }

    def _sync_duels_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            connection_id = UUID(str(payload["connection_id"]))
            max_pages = int(payload.get("max_pages", 25))
        except (KeyError, TypeError, ValueError) as error:
            raise PermanentJobError("duels.sync_connection requires a UUID connection_id") from error
        service = DuelsService.from_engine(self.engine)
        result = service.sync_history(connection_id, max_pages=max_pages)
        pending = service.pending_replays(connection_id, limit=500)
        enqueued = 0
        for row in pending:
            queued = enqueue_duels_replay(
                self.queue,
                connection_id,
                row["game_id"],
                provider_replay_id=row["provider_replay_id"],
                replay_url=row["replay_url"],
            )
            enqueued += int(queued.created)
        if not result.history_exhausted and result.next_cursor:
            enqueue_duels_sync(
                self.queue,
                connection_id,
                generation=f"cursor:{result.next_cursor}",
            )
        return {
            "connection_id": str(connection_id),
            "pages_fetched": result.pages_fetched,
            "games_observed": result.games_observed,
            "new_games": result.new_games,
            "history_exhausted": result.history_exhausted,
            "next_cursor": result.next_cursor,
            "replay_jobs_created": enqueued,
        }

    def _process_duels_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            connection_id = UUID(str(payload["connection_id"]))
            game_id = str(payload["game_id"]).strip()
            force_refresh = bool(payload.get("force_refresh", False))
        except (KeyError, TypeError, ValueError) as error:
            raise PermanentJobError(
                "duels.process_replay requires connection_id and game_id"
            ) from error
        if not game_id:
            raise PermanentJobError("duels.process_replay game_id must not be empty")
        result = DuelsService.from_engine(self.engine).process_replay(
            connection_id,
            game_id,
            force_refresh=force_refresh,
        )
        return {
            "connection_id": str(connection_id),
            "game_id": game_id,
            "replay_id": str(result.replay_id),
            "replay_created": result.replay_created,
            "normalization_id": str(result.normalization_id),
            "normalization_created": result.normalization_created,
            "feature_set_id": str(result.feature_set_id),
            "feature_set_created": result.feature_set_created,
        }

    def _coach_analyze_replay(
        self,
        payload: dict[str, Any],
        *,
        restart_running: bool = False,
    ) -> dict[str, Any]:
        try:
            member_id = UUID(str(payload["member_id"]))
            normalization_id = UUID(str(payload["normalization_id"]))
            feature_set_id = UUID(str(payload["feature_set_id"]))
            catalog_snapshot_id = UUID(str(payload["catalog_snapshot_id"]))
            decklist_raw = payload.get("decklist_id")
            decklist_id = UUID(str(decklist_raw)) if decklist_raw else None
            analyzer_name = str(payload["analyzer_name"]).strip().lower()
            analysis_config = payload.get("analysis_config") or {}
            if not isinstance(analysis_config, dict):
                raise TypeError("analysis_config must be an object")
        except (KeyError, TypeError, ValueError) as error:
            raise PermanentJobError(
                "coach.analyze_replay requires valid member/evidence/catalog UUIDs and analyzer_name"
            ) from error
        if not analyzer_name:
            raise PermanentJobError("coach.analyze_replay analyzer_name must not be empty")
        try:
            analyzer = self.analyzer_registry.create(analyzer_name)
        except AnalyzerNotConfiguredError as error:
            raise PermanentJobError(str(error)) from error
        try:
            result = CoachService.from_engine(self.engine).analyze(
                member_id=member_id,
                normalization_id=normalization_id,
                feature_set_id=feature_set_id,
                catalog_snapshot_id=catalog_snapshot_id,
                decklist_id=decklist_id,
                analyzer=analyzer,
                analysis_config=analysis_config,
                restart_running=restart_running,
            )
        finally:
            close = getattr(analyzer, "close", None)
            if callable(close):
                close()
        return {
            "analysis_run_id": str(result.analysis_run_id),
            "report_id": str(result.report_id),
            "cached": result.cached,
            "finding_count": result.finding_count,
        }

    def _refresh_lorcast_catalog(self) -> dict[str, Any]:
        client = LorcastClient()
        try:
            payload, metadata = client.complete_english_snapshot()
        finally:
            client.close()
        result = CatalogService.from_engine(self.engine).import_snapshot(
            payload,
            source_name="lorcast",
            source_version="v0",
            metadata=metadata,
        )
        return {
            "snapshot_id": str(result.snapshot_id),
            "created": result.created,
            "card_count": result.card_count,
            "source_sha256": result.source_sha256,
        }

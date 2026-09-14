"""Canonical job kind names and enqueue helpers."""

from __future__ import annotations

from datetime import date
import hashlib
import json
from uuid import UUID

from lorcana.jobs.service import JobQueue
from lorcana.jobs.types import EnqueuedJob

PLAYHUB_DISCOVER_DAY = "playhub.discover_day"
PLAYHUB_IMPORT_EVENT = "playhub.import_event"
PLAYHUB_DISCOVER_WINDOW = "playhub.discover_window"
PLAYHUB_IMPORT_SWEEP = "playhub.import_sweep"
RATINGS_BUILD_PUBLISH = "ratings.build_publish"
DUELS_SYNC_CONNECTION = "duels.sync_connection"
DUELS_PROCESS_REPLAY = "duels.process_replay"
COACH_ANALYZE_REPLAY = "coach.analyze_replay"
CATALOG_REFRESH_LORCAST = "catalog.refresh_lorcast"
MAINTENANCE_PRUNE_JOBS = "maintenance.prune_jobs"


def enqueue_discovery(queue: JobQueue, day: date, *, force: bool = False) -> EnqueuedJob:
    key = f"{PLAYHUB_DISCOVER_DAY}:{day.isoformat()}:{'force' if force else 'normal'}"
    return queue.enqueue(
        PLAYHUB_DISCOVER_DAY,
        resource_key=day.isoformat(),
        payload={"day": day.isoformat(), "force": force},
        idempotency_key=key,
        priority=20,
    )


def enqueue_event_import(queue: JobQueue, event_id: int, *, generation: str = "default") -> EnqueuedJob:
    return queue.enqueue(
        PLAYHUB_IMPORT_EVENT,
        resource_key=str(event_id),
        payload={"event_id": int(event_id)},
        idempotency_key=f"{PLAYHUB_IMPORT_EVENT}:{event_id}:{generation}",
        priority=10,
    )


def enqueue_rating_build(
    queue: JobQueue,
    *,
    publication_name: str = "global_elo",
    policy: str = "global",
    generation: str,
) -> EnqueuedJob:
    return queue.enqueue(
        RATINGS_BUILD_PUBLISH,
        resource_key=publication_name,
        payload={"publication_name": publication_name, "policy": policy},
        idempotency_key=f"{RATINGS_BUILD_PUBLISH}:{publication_name}:{generation}",
        priority=5,
        max_attempts=2,
    )


def enqueue_duels_sync(queue: JobQueue, connection_id, *, generation: str) -> EnqueuedJob:
    value = str(connection_id)
    return queue.enqueue(
        DUELS_SYNC_CONNECTION,
        resource_key=value,
        payload={"connection_id": value},
        idempotency_key=f"{DUELS_SYNC_CONNECTION}:{value}:{generation}",
        priority=15,
        max_attempts=4,
    )


def enqueue_duels_replay(
    queue: JobQueue,
    connection_id,
    game_id: str,
    *,
    provider_replay_id: str | None,
    replay_url: str | None = None,
    generation: str | None = None,
    force_refresh: bool = False,
) -> EnqueuedJob:
    import hashlib
    connection_value = str(connection_id)
    identity = provider_replay_id
    if identity is None:
        identity = hashlib.sha256((replay_url or game_id).encode("utf-8")).hexdigest()[:24]
    if generation:
        identity = f"{identity}:{generation}"
    return queue.enqueue(
        DUELS_PROCESS_REPLAY,
        resource_key=f"{connection_value}:{game_id}",
        payload={
            "connection_id": connection_value,
            "game_id": game_id,
            "force_refresh": bool(force_refresh),
        },
        idempotency_key=f"{DUELS_PROCESS_REPLAY}:{connection_value}:{game_id}:{identity}",
        priority=12,
        max_attempts=4,
    )


def enqueue_coach_analysis(
    queue: JobQueue,
    *,
    member_id: UUID,
    normalization_id: UUID,
    feature_set_id: UUID,
    catalog_snapshot_id: UUID,
    analyzer_name: str,
    analyzer_generation: str = "v1",
    decklist_id: UUID | None = None,
    analysis_config: dict | None = None,
) -> EnqueuedJob:
    name = analyzer_name.strip().lower()
    if not name:
        raise ValueError("analyzer_name must not be empty")
    generation = analyzer_generation.strip()
    if not generation:
        raise ValueError("analyzer_generation must not be empty")
    payload = {
        "member_id": str(member_id),
        "normalization_id": str(normalization_id),
        "feature_set_id": str(feature_set_id),
        "catalog_snapshot_id": str(catalog_snapshot_id),
        "decklist_id": str(decklist_id) if decklist_id else None,
        "analyzer_name": name,
        "analyzer_generation": generation,
        "analysis_config": dict(analysis_config or {}),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return queue.enqueue(
        COACH_ANALYZE_REPLAY,
        resource_key=f"{member_id}:{normalization_id}",
        payload=payload,
        idempotency_key=f"{COACH_ANALYZE_REPLAY}:{digest}",
        priority=8,
        max_attempts=3,
    )


def enqueue_catalog_refresh(queue: JobQueue, *, generation: str) -> EnqueuedJob:
    value = generation.strip()
    if not value:
        raise ValueError("catalog refresh generation must not be empty")
    return queue.enqueue(
        CATALOG_REFRESH_LORCAST,
        resource_key="lorcast",
        payload={},
        idempotency_key=f"{CATALOG_REFRESH_LORCAST}:{value}",
        priority=4,
        max_attempts=4,
    )

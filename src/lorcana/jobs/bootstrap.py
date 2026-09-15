"""Supported recurring schedule definitions for a fresh platform deployment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy.engine import Engine

from lorcana.jobs.kinds import (
    CATALOG_REFRESH_LORCAST,
    DUELS_SYNC_CONNECTION,
    MAINTENANCE_PRUNE_JOBS,
    PLAYHUB_DISCOVER_WINDOW,
    PLAYHUB_IMPORT_SWEEP,
    RATINGS_BUILD_PUBLISH,
)
from lorcana.jobs.schedule import ScheduledJobService


@dataclass(frozen=True, slots=True)
class ScheduleDefinition:
    name: str
    kind: str
    schedule_spec: Mapping[str, Any]
    payload: Mapping[str, Any]
    resource_key: str | None = None
    priority: int = 0
    max_attempts: int = 3
    enabled: bool = True


def default_platform_schedules() -> tuple[ScheduleDefinition, ...]:
    """Return safe, editable defaults for globally shared recurring work.

    Duels account syncs are intentionally excluded because they are scoped to a
    specific connection. Use ``upsert_duels_sync_schedule`` after provisioning
    each connection.
    """

    return (
        ScheduleDefinition(
            name="playhub-discover-upcoming",
            kind=PLAYHUB_DISCOVER_WINDOW,
            schedule_spec={"type": "daily", "hour": 2, "minute": 0, "timezone": "UTC"},
            payload={
                "anchor_date": "$scheduled_date",
                "lookback_days": 30,
                "lookahead_days": 30,
                "chunk_days": 7,
                "force": False,
            },
            resource_key="global",
            priority=20,
            max_attempts=4,
        ),
        ScheduleDefinition(
            name="playhub-import-sweep",
            kind=PLAYHUB_IMPORT_SWEEP,
            schedule_spec={"type": "interval", "seconds": 2 * 60 * 60},
            payload={
                "lookback_days": 90,
                "retry_minutes": 180,
                "limit": 500,
                "generation": "$scheduled_at",
            },
            resource_key="global",
            priority=15,
            max_attempts=3,
        ),
        ScheduleDefinition(
            name="ratings-global-daily",
            kind=RATINGS_BUILD_PUBLISH,
            schedule_spec={"type": "daily", "hour": 8, "minute": 0, "timezone": "UTC"},
            payload={"publication_name": "global_elo", "policy": "global"},
            resource_key="global_elo",
            priority=5,
            max_attempts=2,
        ),
        ScheduleDefinition(
            name="maintenance-prune-jobs",
            kind=MAINTENANCE_PRUNE_JOBS,
            schedule_spec={"type": "daily", "hour": 6, "minute": 30, "timezone": "UTC"},
            payload={"retention_days": 30, "limit": 5_000},
            resource_key="jobs",
            priority=1,
            max_attempts=3,
        ),
        ScheduleDefinition(
            name="catalog-lorcast-daily",
            kind=CATALOG_REFRESH_LORCAST,
            schedule_spec={"type": "daily", "hour": 7, "minute": 0, "timezone": "UTC"},
            payload={},
            resource_key="lorcast",
            priority=4,
            max_attempts=4,
        ),
    )


def bootstrap_platform_schedules(engine: Engine) -> tuple[tuple[str, UUID], ...]:
    service = ScheduledJobService.from_engine(engine)
    results: list[tuple[str, UUID]] = []
    for definition in default_platform_schedules():
        scheduled_job_id = service.upsert(
            definition.name,
            definition.kind,
            schedule_spec=definition.schedule_spec,
            payload=definition.payload,
            resource_key=definition.resource_key,
            priority=definition.priority,
            max_attempts=definition.max_attempts,
            enabled=definition.enabled,
        )
        results.append((definition.name, scheduled_job_id))
    return tuple(results)


def upsert_duels_sync_schedule(
    engine: Engine,
    connection_id: UUID,
    *,
    interval_hours: int = 6,
    enabled: bool = True,
) -> UUID:
    if not 1 <= interval_hours <= 168:
        raise ValueError("Duels sync interval_hours must be between 1 and 168")
    value = str(connection_id)
    return ScheduledJobService.from_engine(engine).upsert(
        f"duels-sync-{value}",
        DUELS_SYNC_CONNECTION,
        schedule_spec={"type": "interval", "seconds": interval_hours * 60 * 60},
        payload={"connection_id": value},
        resource_key=value,
        priority=15,
        max_attempts=4,
        enabled=enabled,
    )

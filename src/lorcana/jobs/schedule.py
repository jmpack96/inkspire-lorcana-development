"""Durable schedule definitions and due-job materialization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta, timezone
from typing import Any, ContextManager
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, Engine

from lorcana.db.schema.jobs import scheduled_jobs
from lorcana.db.tx import transaction
from lorcana.jobs.repository import JobRepository

Clock = Callable[[], datetime]
UUIDFactory = Callable[[], UUID]
TransactionFactory = Callable[[], ContextManager[Connection]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)




def materialize_scheduled_payload(value: Any, scheduled_for: datetime) -> Any:
    """Replace reserved schedule placeholders with occurrence-specific values."""
    if scheduled_for.tzinfo is None or scheduled_for.utcoffset() is None:
        raise ValueError("scheduled_for must be timezone-aware")
    utc = scheduled_for.astimezone(timezone.utc)
    if isinstance(value, str):
        if value == "$scheduled_at":
            return utc.isoformat()
        if value == "$scheduled_date":
            return utc.date().isoformat()
        return value
    if isinstance(value, list):
        return [materialize_scheduled_payload(item, utc) for item in value]
    if isinstance(value, tuple):
        return [materialize_scheduled_payload(item, utc) for item in value]
    if isinstance(value, Mapping):
        return {key: materialize_scheduled_payload(item, utc) for key, item in value.items()}
    return value

def next_occurrence(schedule_spec: Mapping[str, Any], after: datetime) -> datetime:
    """Return the first UTC occurrence strictly after *after*.

    Initial scheduler support intentionally covers the two cases the platform
    needs: fixed intervals and a daily local wall-clock time.
    """
    if after.tzinfo is None or after.utcoffset() is None:
        raise ValueError("after must be timezone-aware")
    kind = schedule_spec.get("type")
    if kind == "interval":
        seconds = int(schedule_spec.get("seconds", 0))
        if seconds < 60:
            raise ValueError("interval schedules must be at least 60 seconds")
        return after.astimezone(timezone.utc) + timedelta(seconds=seconds)
    if kind == "daily":
        hour = int(schedule_spec.get("hour", -1))
        minute = int(schedule_spec.get("minute", -1))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("daily schedule hour/minute are invalid")
        zone_name = str(schedule_spec.get("timezone", "UTC"))
        try:
            zone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"Unknown schedule timezone: {zone_name}") from error
        local_after = after.astimezone(zone)
        candidate = datetime.combine(local_after.date(), time(hour, minute), tzinfo=zone)
        if candidate <= local_after:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    raise ValueError(f"Unsupported schedule type: {kind!r}")


class ScheduleRepository:
    def upsert(
        self,
        connection: Connection,
        *,
        scheduled_job_id: UUID,
        name: str,
        kind: str,
        resource_key: str | None,
        payload: Mapping[str, Any],
        schedule_spec: Mapping[str, Any],
        priority: int,
        max_attempts: int,
        enabled: bool,
        next_run_at: datetime,
        now: datetime,
    ) -> UUID:
        statement = insert(scheduled_jobs).values(
            scheduled_job_id=scheduled_job_id,
            name=name,
            kind=kind,
            resource_key=resource_key,
            payload=dict(payload),
            schedule_spec=dict(schedule_spec),
            priority=priority,
            max_attempts=max_attempts,
            enabled=enabled,
            next_run_at=next_run_at,
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[scheduled_jobs.c.name],
            set_={
                "kind": statement.excluded.kind,
                "resource_key": statement.excluded.resource_key,
                "payload": statement.excluded.payload,
                "schedule_spec": statement.excluded.schedule_spec,
                "priority": statement.excluded.priority,
                "max_attempts": statement.excluded.max_attempts,
                "enabled": statement.excluded.enabled,
                "next_run_at": statement.excluded.next_run_at,
                "updated_at": statement.excluded.updated_at,
            },
        ).returning(scheduled_jobs.c.scheduled_job_id)
        return connection.execute(statement).scalar_one()

    def next_due(self, connection: Connection, *, now: datetime):
        return connection.execute(
            select(scheduled_jobs)
            .where(scheduled_jobs.c.enabled.is_(True), scheduled_jobs.c.next_run_at <= now)
            .order_by(scheduled_jobs.c.next_run_at, scheduled_jobs.c.name)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).mappings().one_or_none()

    def advance(
        self,
        connection: Connection,
        *,
        scheduled_job_id: UUID,
        scheduled_for: datetime,
        next_run_at: datetime,
        now: datetime,
    ) -> None:
        connection.execute(
            update(scheduled_jobs)
            .where(scheduled_jobs.c.scheduled_job_id == scheduled_job_id)
            .values(
                last_enqueued_at=scheduled_for,
                next_run_at=next_run_at,
                updated_at=now,
            )
        )


class ScheduledJobService:
    def __init__(
        self,
        *,
        schedule_repository: ScheduleRepository,
        job_repository: JobRepository,
        transaction_factory: TransactionFactory,
        clock: Clock = utc_now,
        uuid_factory: UUIDFactory = uuid4,
    ) -> None:
        self.schedule_repository = schedule_repository
        self.job_repository = job_repository
        self.transaction_factory = transaction_factory
        self.clock = clock
        self.uuid_factory = uuid_factory

    @classmethod
    def from_engine(cls, engine: Engine, **kwargs: Any) -> "ScheduledJobService":
        return cls(
            schedule_repository=ScheduleRepository(),
            job_repository=JobRepository(),
            transaction_factory=lambda: transaction(engine),
            **kwargs,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ScheduledJobService clock must return timezone-aware datetimes")
        return value.astimezone(timezone.utc)

    def upsert(
        self,
        name: str,
        kind: str,
        *,
        schedule_spec: Mapping[str, Any],
        payload: Mapping[str, Any] | None = None,
        resource_key: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        enabled: bool = True,
    ) -> UUID:
        if not name.strip() or not kind.strip():
            raise ValueError("schedule name and job kind must not be empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        now = self._now()
        next_run = next_occurrence(schedule_spec, now)
        with self.transaction_factory() as connection:
            return self.schedule_repository.upsert(
                connection,
                scheduled_job_id=self.uuid_factory(),
                name=name.strip(),
                kind=kind.strip(),
                resource_key=resource_key,
                payload=payload or {},
                schedule_spec=schedule_spec,
                priority=priority,
                max_attempts=max_attempts,
                enabled=enabled,
                next_run_at=next_run,
                now=now,
            )

    def enqueue_due(self, *, limit: int = 25) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        materialized = 0
        for _ in range(limit):
            now = self._now()
            with self.transaction_factory() as connection:
                row = self.schedule_repository.next_due(connection, now=now)
                if row is None:
                    break
                scheduled_for = row["next_run_at"]
                occurrence_key = f"schedule:{row['scheduled_job_id']}:{scheduled_for.astimezone(timezone.utc).isoformat()}"
                self.job_repository.enqueue(
                    connection,
                    job_id=self.uuid_factory(),
                    kind=row["kind"],
                    resource_key=row["resource_key"],
                    payload=materialize_scheduled_payload(row["payload"], scheduled_for),
                    idempotency_key=occurrence_key,
                    priority=row["priority"],
                    max_attempts=row["max_attempts"],
                    available_at=scheduled_for,
                    created_at=now,
                )
                following = next_occurrence(row["schedule_spec"], scheduled_for)
                self.schedule_repository.advance(
                    connection,
                    scheduled_job_id=row["scheduled_job_id"],
                    scheduled_for=scheduled_for,
                    next_run_at=following,
                    now=now,
                )
                materialized += 1
        return materialized

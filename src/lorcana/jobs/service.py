"""Application service for enqueueing and leasing durable jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, ContextManager
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection, Engine

from lorcana.db.tx import transaction
from lorcana.jobs.repository import JobRepository
from lorcana.jobs.types import EnqueuedJob, JobFailureResult, JobLease

Clock = Callable[[], datetime]
UUIDFactory = Callable[[], UUID]
TransactionFactory = Callable[[], ContextManager[Connection]]


class JobLeaseLostError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobQueue:
    def __init__(
        self,
        *,
        repository: JobRepository,
        transaction_factory: TransactionFactory,
        clock: Clock = utc_now,
        uuid_factory: UUIDFactory = uuid4,
        lease_seconds: int = 300,
    ) -> None:
        if lease_seconds < 30:
            raise ValueError("lease_seconds must be at least 30")
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.clock = clock
        self.uuid_factory = uuid_factory
        self.lease_seconds = lease_seconds

    @classmethod
    def from_engine(cls, engine: Engine, **kwargs: Any) -> "JobQueue":
        return cls(
            repository=JobRepository(),
            transaction_factory=lambda: transaction(engine),
            **kwargs,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("JobQueue clock must return timezone-aware datetimes")
        return value.astimezone(timezone.utc)

    def enqueue(
        self,
        kind: str,
        *,
        payload: Mapping[str, Any] | None = None,
        resource_key: str | None = None,
        idempotency_key: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        available_at: datetime | None = None,
    ) -> EnqueuedJob:
        if not kind.strip():
            raise ValueError("job kind must not be empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        now = self._now()
        available = available_at or now
        if available.tzinfo is None or available.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        with self.transaction_factory() as connection:
            job_id, created = self.repository.enqueue(
                connection,
                job_id=self.uuid_factory(),
                kind=kind.strip(),
                resource_key=resource_key,
                payload=payload or {},
                idempotency_key=idempotency_key,
                priority=int(priority),
                max_attempts=max_attempts,
                available_at=available.astimezone(timezone.utc),
                created_at=now,
            )
        return EnqueuedJob(job_id=job_id, created=created)

    def claim(self, worker_id: str) -> JobLease | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        now = self._now()
        token = self.uuid_factory()
        expires = now + timedelta(seconds=self.lease_seconds)
        with self.transaction_factory() as connection:
            row = self.repository.claim(
                connection,
                worker_id=worker_id,
                lease_token=token,
                now=now,
                lease_expires_at=expires,
            )
        return None if row is None else JobLease(**row)

    def heartbeat(self, lease: JobLease, *, progress: Mapping[str, Any] | None = None) -> JobLease:
        now = self._now()
        expires = now + timedelta(seconds=self.lease_seconds)
        with self.transaction_factory() as connection:
            ok = self.repository.heartbeat(
                connection,
                job_id=lease.job_id,
                lease_token=lease.lease_token,
                now=now,
                lease_expires_at=expires,
                progress=progress,
            )
        if not ok:
            raise JobLeaseLostError(f"Lease lost for job {lease.job_id}")
        return JobLease(**{**lease.__dict__, "lease_expires_at": expires})

    def succeed(self, lease: JobLease, *, progress: Mapping[str, Any] | None = None) -> None:
        now = self._now()
        with self.transaction_factory() as connection:
            ok = self.repository.succeed(
                connection,
                job_id=lease.job_id,
                lease_token=lease.lease_token,
                now=now,
                progress=progress,
            )
        if not ok:
            raise JobLeaseLostError(f"Lease lost for job {lease.job_id}")

    def fail(
        self,
        lease: JobLease,
        error: Exception,
        *,
        retryable: bool = True,
        retry_delay_seconds: int = 60,
    ) -> JobFailureResult:
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        now = self._now()
        retry_at = None
        if retryable and lease.attempt_number < lease.max_attempts:
            retry_at = now + timedelta(seconds=retry_delay_seconds)
        category = type(error).__name__[:200]
        summary = str(error)[:4_000]
        with self.transaction_factory() as connection:
            ok = self.repository.fail(
                connection,
                job_id=lease.job_id,
                lease_token=lease.lease_token,
                now=now,
                retry_at=retry_at,
                error_category=category,
                error_summary=summary,
            )
        if not ok:
            raise JobLeaseLostError(f"Lease lost for job {lease.job_id}")
        return JobFailureResult(
            job_id=lease.job_id,
            status="queued" if retry_at is not None else "failed",
            retry_at=retry_at,
        )

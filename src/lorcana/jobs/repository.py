"""PostgreSQL persistence for durable job leases."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from lorcana.db.schema.jobs import job_attempts, jobs


class JobRepository:
    def enqueue(
        self,
        connection: Connection,
        *,
        job_id: UUID,
        kind: str,
        resource_key: str | None,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
        priority: int,
        max_attempts: int,
        available_at: datetime,
        created_at: datetime,
    ) -> tuple[UUID, bool]:
        values = dict(
            job_id=job_id,
            kind=kind,
            resource_key=resource_key,
            payload=dict(payload),
            idempotency_key=idempotency_key,
            status="queued",
            priority=priority,
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=available_at,
            created_at=created_at,
            updated_at=created_at,
        )
        if idempotency_key is None:
            connection.execute(jobs.insert().values(**values))
            return job_id, True

        statement = (
            insert(jobs)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[jobs.c.idempotency_key])
            .returning(jobs.c.job_id)
        )
        created_id = connection.execute(statement).scalar_one_or_none()
        if created_id is not None:
            return created_id, True
        existing = connection.execute(
            select(jobs.c.job_id).where(jobs.c.idempotency_key == idempotency_key)
        ).scalar_one()
        return existing, False


    def prune_completed_before(
        self,
        connection: Connection,
        *,
        completed_before: datetime,
        limit: int,
    ) -> int:
        """Delete a bounded batch of terminal operational jobs and attempts."""
        doomed = tuple(
            connection.execute(
                select(jobs.c.job_id)
                .where(
                    jobs.c.status.in_(["succeeded", "failed", "cancelled"]),
                    jobs.c.completed_at.is_not(None),
                    jobs.c.completed_at < completed_before,
                )
                .order_by(jobs.c.completed_at, jobs.c.job_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).scalars().all()
        )
        if not doomed:
            return 0
        connection.execute(delete(job_attempts).where(job_attempts.c.job_id.in_(doomed)))
        connection.execute(delete(jobs).where(jobs.c.job_id.in_(doomed)))
        return len(doomed)

    def expire_exhausted_leases(self, connection: Connection, *, now: datetime) -> int:
        expired = connection.execute(
            select(jobs.c.job_id, jobs.c.lease_token, jobs.c.attempt_count)
            .where(
                jobs.c.status == "running",
                jobs.c.lease_expires_at <= now,
                jobs.c.attempt_count >= jobs.c.max_attempts,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for job_id, lease_token, attempt_number in expired:
            connection.execute(
                update(jobs)
                .where(jobs.c.job_id == job_id, jobs.c.lease_token == lease_token)
                .values(
                    status="failed",
                    completed_at=now,
                    updated_at=now,
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                    last_error_category="lease_expired",
                    last_error_summary="Worker lease expired after the final allowed attempt.",
                )
            )
            connection.execute(
                update(job_attempts)
                .where(
                    job_attempts.c.job_id == job_id,
                    job_attempts.c.attempt_number == attempt_number,
                    job_attempts.c.status == "running",
                )
                .values(
                    status="lease_expired",
                    completed_at=now,
                    error_category="lease_expired",
                    error_summary="Worker lease expired.",
                )
            )
        return len(expired)

    def claim(
        self,
        connection: Connection,
        *,
        worker_id: str,
        lease_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
    ):
        self.expire_exhausted_leases(connection, now=now)
        claimable = or_(
            and_(jobs.c.status == "queued", jobs.c.available_at <= now),
            and_(
                jobs.c.status == "running",
                jobs.c.lease_expires_at <= now,
                jobs.c.attempt_count < jobs.c.max_attempts,
            ),
        )
        row = connection.execute(
            select(jobs)
            .where(claimable)
            .order_by(jobs.c.priority.desc(), jobs.c.available_at, jobs.c.created_at, jobs.c.job_id)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).mappings().one_or_none()
        if row is None:
            return None

        if row["status"] == "running" and row["lease_token"] is not None:
            connection.execute(
                update(job_attempts)
                .where(
                    job_attempts.c.job_id == row["job_id"],
                    job_attempts.c.attempt_number == row["attempt_count"],
                    job_attempts.c.status == "running",
                )
                .values(
                    status="lease_expired",
                    completed_at=now,
                    error_category="lease_expired",
                    error_summary="Worker lease expired and the job was reclaimed.",
                )
            )

        attempt_number = int(row["attempt_count"]) + 1
        connection.execute(
            update(jobs)
            .where(jobs.c.job_id == row["job_id"])
            .values(
                status="running",
                attempt_count=attempt_number,
                lease_owner=worker_id,
                lease_token=lease_token,
                lease_expires_at=lease_expires_at,
                updated_at=now,
                last_error_category=None,
                last_error_summary=None,
            )
        )
        connection.execute(
            job_attempts.insert().values(
                job_id=row["job_id"],
                attempt_number=attempt_number,
                lease_token=lease_token,
                worker_id=worker_id,
                started_at=now,
                status="running",
            )
        )
        return {
            "job_id": row["job_id"],
            "kind": row["kind"],
            "resource_key": row["resource_key"],
            "payload": dict(row["payload"]),
            "attempt_number": attempt_number,
            "max_attempts": row["max_attempts"],
            "lease_owner": worker_id,
            "lease_token": lease_token,
            "lease_expires_at": lease_expires_at,
        }

    def heartbeat(
        self,
        connection: Connection,
        *,
        job_id: UUID,
        lease_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
        progress: Mapping[str, Any] | None,
    ) -> bool:
        values: dict[str, Any] = {
            "lease_expires_at": lease_expires_at,
            "updated_at": now,
        }
        if progress is not None:
            values["progress"] = dict(progress)
        result = connection.execute(
            update(jobs)
            .where(
                jobs.c.job_id == job_id,
                jobs.c.status == "running",
                jobs.c.lease_token == lease_token,
            )
            .values(**values)
        )
        return result.rowcount == 1

    def succeed(
        self,
        connection: Connection,
        *,
        job_id: UUID,
        lease_token: UUID,
        now: datetime,
        progress: Mapping[str, Any] | None,
    ) -> bool:
        result = connection.execute(
            update(jobs)
            .where(
                jobs.c.job_id == job_id,
                jobs.c.status == "running",
                jobs.c.lease_token == lease_token,
            )
            .values(
                status="succeeded",
                progress=None if progress is None else dict(progress),
                completed_at=now,
                updated_at=now,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
            )
        )
        if result.rowcount != 1:
            return False
        connection.execute(
            update(job_attempts)
            .where(job_attempts.c.job_id == job_id, job_attempts.c.lease_token == lease_token)
            .values(status="succeeded", completed_at=now)
        )
        return True

    def fail(
        self,
        connection: Connection,
        *,
        job_id: UUID,
        lease_token: UUID,
        now: datetime,
        retry_at: datetime | None,
        error_category: str,
        error_summary: str,
    ) -> bool:
        current = connection.execute(
            select(jobs.c.attempt_count, jobs.c.max_attempts)
            .where(
                jobs.c.job_id == job_id,
                jobs.c.status == "running",
                jobs.c.lease_token == lease_token,
            )
            .with_for_update()
        ).one_or_none()
        if current is None:
            return False
        can_retry = retry_at is not None and current.attempt_count < current.max_attempts
        values: dict[str, Any] = {
            "status": "queued" if can_retry else "failed",
            "updated_at": now,
            "completed_at": None if can_retry else now,
            "lease_owner": None,
            "lease_token": None,
            "lease_expires_at": None,
            "last_error_category": error_category,
            "last_error_summary": error_summary,
        }
        if can_retry:
            values["available_at"] = retry_at
        connection.execute(update(jobs).where(jobs.c.job_id == job_id).values(**values))
        connection.execute(
            update(job_attempts)
            .where(job_attempts.c.job_id == job_id, job_attempts.c.lease_token == lease_token)
            .values(
                status="failed",
                completed_at=now,
                error_category=error_category,
                error_summary=error_summary,
            )
        )
        return True

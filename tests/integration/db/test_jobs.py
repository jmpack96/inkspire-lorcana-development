from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from lorcana.db.schema.jobs import job_attempts, jobs
from lorcana.jobs.service import JobLeaseLostError, JobQueue

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)


def _clear(engine):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE job_attempts, jobs CASCADE"))


def test_idempotent_enqueue_and_lease_fencing(db_engine):
    _clear(db_engine)
    clock = {"now": NOW}
    try:
        queue = JobQueue.from_engine(
            db_engine,
            clock=lambda: clock["now"],
            lease_seconds=30,
        )
        first = queue.enqueue("example", payload={"x": 1}, idempotency_key="same")
        duplicate = queue.enqueue("example", payload={"x": 2}, idempotency_key="same")
        assert first.created is True
        assert duplicate.created is False
        assert duplicate.job_id == first.job_id

        lease1 = queue.claim("worker-1")
        assert lease1 is not None
        clock["now"] = NOW + timedelta(seconds=31)
        lease2 = queue.claim("worker-2")
        assert lease2 is not None
        assert lease2.job_id == lease1.job_id
        assert lease2.lease_token != lease1.lease_token
        assert lease2.attempt_number == 2

        with pytest.raises(JobLeaseLostError):
            queue.succeed(lease1)
        queue.succeed(lease2, progress={"ok": True})

        with db_engine.connect() as connection:
            row = connection.execute(select(jobs).where(jobs.c.job_id == first.job_id)).mappings().one()
            assert row["status"] == "succeeded"
            attempts = connection.execute(
                select(job_attempts.c.attempt_number, job_attempts.c.status)
                .where(job_attempts.c.job_id == first.job_id)
                .order_by(job_attempts.c.attempt_number)
            ).all()
            assert attempts == [(1, "lease_expired"), (2, "succeeded")]
    finally:
        _clear(db_engine)


def test_terminal_job_history_can_be_pruned_in_bounded_batches(db_engine):
    from lorcana.jobs.repository import JobRepository

    _clear(db_engine)
    old = NOW - timedelta(days=45)
    try:
        queue = JobQueue.from_engine(db_engine, clock=lambda: old, lease_seconds=30)
        queued = queue.enqueue("old-job")
        lease = queue.claim("worker")
        assert lease is not None
        queue.succeed(lease)

        with db_engine.begin() as connection:
            deleted = JobRepository().prune_completed_before(
                connection,
                completed_before=NOW - timedelta(days=30),
                limit=100,
            )
        assert deleted == 1
        with db_engine.connect() as connection:
            assert connection.execute(
                select(jobs.c.job_id).where(jobs.c.job_id == queued.job_id)
            ).scalar_one_or_none() is None
            assert connection.execute(
                select(job_attempts.c.job_id).where(job_attempts.c.job_id == queued.job_id)
            ).scalar_one_or_none() is None
    finally:
        _clear(db_engine)

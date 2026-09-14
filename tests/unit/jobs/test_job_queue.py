from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from lorcana.jobs.service import JobLeaseLostError, JobQueue
from lorcana.jobs.types import JobLease

NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)
JOB_ID = UUID("00000000-0000-0000-0000-000000000501")
TOKEN = UUID("00000000-0000-0000-0000-000000000502")


class FakeRepository:
    def __init__(self):
        self.enqueued = None
        self.claimed = None
        self.heartbeat_ok = True
        self.succeed_ok = True
        self.fail_ok = True
        self.failed = None

    def enqueue(self, _c, **values):
        self.enqueued = values
        return values["job_id"], True

    def claim(self, _c, **values):
        self.claimed = values
        return {
            "job_id": JOB_ID,
            "kind": "test",
            "resource_key": None,
            "payload": {"x": 1},
            "attempt_number": 1,
            "max_attempts": 3,
            "lease_owner": values["worker_id"],
            "lease_token": values["lease_token"],
            "lease_expires_at": values["lease_expires_at"],
        }

    def heartbeat(self, _c, **values):
        return self.heartbeat_ok

    def succeed(self, _c, **values):
        return self.succeed_ok

    def fail(self, _c, **values):
        self.failed = values
        return self.fail_ok


@contextmanager
def tx():
    yield object()


def queue(repo, *, uuids=(JOB_ID, TOKEN)):
    values = iter(uuids)
    return JobQueue(
        repository=repo,
        transaction_factory=tx,
        clock=lambda: NOW,
        uuid_factory=lambda: next(values),
        lease_seconds=300,
    )


def test_enqueue_and_claim_create_a_fenced_lease():
    repo = FakeRepository()
    q = queue(repo)
    enqueued = q.enqueue("test", payload={"x": 1}, idempotency_key="same")
    assert enqueued.job_id == JOB_ID
    assert enqueued.created is True

    lease = q.claim("worker-1")
    assert lease.kind == "test"
    assert lease.lease_token == TOKEN
    assert lease.attempt_number == 1
    assert int((lease.lease_expires_at - NOW).total_seconds()) == 300


def test_fail_requeues_before_max_attempts_and_terminally_fails_at_max():
    repo = FakeRepository()
    q = queue(repo, uuids=(TOKEN,))
    lease = JobLease(JOB_ID, "test", None, {}, 1, 3, "worker", TOKEN, NOW)
    result = q.fail(lease, RuntimeError("boom"), retry_delay_seconds=45)
    assert result.status == "queued"
    assert int((result.retry_at - NOW).total_seconds()) == 45
    assert repo.failed["error_category"] == "RuntimeError"

    final = JobLease(JOB_ID, "test", None, {}, 3, 3, "worker", TOKEN, NOW)
    result = q.fail(final, RuntimeError("boom"), retry_delay_seconds=45)
    assert result.status == "failed"
    assert result.retry_at is None


def test_stale_lease_completion_is_rejected():
    repo = FakeRepository()
    repo.succeed_ok = False
    q = queue(repo, uuids=(TOKEN,))
    lease = JobLease(JOB_ID, "test", None, {}, 1, 3, "worker", TOKEN, NOW)
    with pytest.raises(JobLeaseLostError):
        q.succeed(lease)


def test_configuration_validation():
    repo = FakeRepository()
    with pytest.raises(ValueError, match="lease_seconds"):
        JobQueue(repository=repo, transaction_factory=tx, lease_seconds=1)
    q = queue(repo)
    with pytest.raises(ValueError, match="kind"):
        q.enqueue("  ")

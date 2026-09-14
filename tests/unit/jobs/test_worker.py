from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from lorcana.jobs.executor import PermanentJobError
from lorcana.jobs.types import JobFailureResult, JobLease
from lorcana.jobs.worker import Worker

NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)
LEASE = JobLease(
    job_id=UUID("00000000-0000-0000-0000-000000000601"),
    kind="test",
    resource_key=None,
    payload={},
    attempt_number=1,
    max_attempts=3,
    lease_owner="worker",
    lease_token=UUID("00000000-0000-0000-0000-000000000602"),
    lease_expires_at=NOW,
)


class Queue:
    lease_seconds = 900

    def __init__(self, lease=LEASE):
        self.lease = lease
        self.success = None
        self.failure = None
        self.heartbeats = 0

    def claim(self, worker_id):
        lease, self.lease = self.lease, None
        return lease

    def heartbeat(self, lease):
        self.heartbeats += 1
        return lease

    def succeed(self, lease, *, progress=None):
        self.success = (lease, progress)

    def fail(self, lease, error, *, retryable=True, retry_delay_seconds=60):
        self.failure = (lease, error, retryable, retry_delay_seconds)
        return JobFailureResult(lease.job_id, "queued" if retryable else "failed", NOW if retryable else None)


class Executor:
    def __init__(self, outcome=None, error=None):
        self.outcome = outcome or {"ok": True}
        self.error = error

    def execute(self, lease):
        if self.error:
            raise self.error
        return self.outcome


def test_worker_completes_successful_job():
    queue = Queue()
    worker = Worker(queue=queue, executor=Executor({"done": 1}), worker_id="worker")
    assert worker.run_once() is True
    assert queue.success[1] == {"done": 1}
    assert queue.failure is None


def test_worker_marks_permanent_error_without_retry():
    queue = Queue()
    worker = Worker(
        queue=queue,
        executor=Executor(error=PermanentJobError("bad payload")),
        worker_id="worker",
    )
    assert worker.run_once() is True
    assert queue.failure[2] is False


def test_worker_retries_transient_error_with_exponential_delay():
    retry_lease = JobLease(**{**LEASE.__dict__, "attempt_number": 2})
    queue = Queue(retry_lease)
    worker = Worker(queue=queue, executor=Executor(error=RuntimeError("network")), worker_id="worker")
    assert worker.run_once() is True
    assert queue.failure[2] is True
    assert queue.failure[3] == 120


def test_worker_returns_false_when_queue_is_empty():
    queue = Queue(None)
    worker = Worker(queue=queue, executor=Executor(), worker_id="worker")
    assert worker.run_once() is False

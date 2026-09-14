"""Single-process durable job worker.

The worker deliberately starts with concurrency=1. Database job leases make
restarts safe and allow future horizontal scaling without putting scheduling in
Discord.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from lorcana.bootstrap import ApplicationResources
from lorcana.coach.runtime import build_analyzer_registry
from lorcana.jobs.executor import PermanentJobError, PlatformJobExecutor
from lorcana.jobs.schedule import ScheduledJobService
from lorcana.jobs.service import JobLeaseLostError, JobQueue
from lorcana.jobs.types import JobLease

logger = logging.getLogger(__name__)


@dataclass
class _HeartbeatState:
    error: Exception | None = None


class LeaseHeartbeat:
    def __init__(self, queue: JobQueue, lease: JobLease, *, interval_seconds: float) -> None:
        self.queue = queue
        self.lease = lease
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._state = _HeartbeatState()
        self._thread = threading.Thread(target=self._run, name=f"job-heartbeat-{lease.job_id}", daemon=True)

    def __enter__(self) -> "LeaseHeartbeat":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        self._thread.join(timeout=max(self.interval_seconds * 2, 1.0))

    @property
    def error(self) -> Exception | None:
        return self._state.error

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.queue.heartbeat(self.lease)
            except Exception as error:  # lease loss / DB outage both stop completion
                self._state.error = error
                self._stop.set()
                return


class Worker:
    def __init__(
        self,
        *,
        queue: JobQueue,
        executor: PlatformJobExecutor,
        worker_id: str,
        poll_seconds: float = 5.0,
        sleeper: Callable[[float], None] = time.sleep,
        scheduler: ScheduledJobService | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.queue = queue
        self.executor = executor
        self.worker_id = worker_id
        self.poll_seconds = poll_seconds
        self.sleeper = sleeper
        self.scheduler = scheduler

    def run_once(self) -> bool:
        if self.scheduler is not None:
            try:
                self.scheduler.enqueue_due(limit=25)
            except Exception:
                logger.exception("Failed to materialize due scheduled jobs")
        lease = self.queue.claim(self.worker_id)
        if lease is None:
            return False
        logger.info(
            "Claimed job %s kind=%s attempt=%d/%d",
            lease.job_id,
            lease.kind,
            lease.attempt_number,
            lease.max_attempts,
        )
        heartbeat_interval = max(10.0, self.queue.lease_seconds / 3)
        try:
            with LeaseHeartbeat(self.queue, lease, interval_seconds=heartbeat_interval) as heartbeat:
                progress = self.executor.execute(lease)
            if heartbeat.error is not None:
                raise JobLeaseLostError(
                    f"Heartbeat failed for job {lease.job_id}: {heartbeat.error}"
                )
            self.queue.succeed(lease, progress=progress)
            logger.info("Completed job %s kind=%s", lease.job_id, lease.kind)
        except JobLeaseLostError:
            logger.exception("Lease lost for job %s; refusing stale completion", lease.job_id)
        except PermanentJobError as error:
            self.queue.fail(lease, error, retryable=False)
            logger.error("Permanent job failure %s: %s", lease.job_id, error)
        except Exception as error:
            # Exponential retry starts at one minute and caps at one hour.
            delay = min(60 * (2 ** max(lease.attempt_number - 1, 0)), 3600)
            result = self.queue.fail(
                lease,
                error,
                retryable=True,
                retry_delay_seconds=delay,
            )
            logger.exception(
                "Job %s failed; status=%s retry_at=%s",
                lease.job_id,
                result.status,
                result.retry_at,
            )
        return True

    def run_forever(self) -> None:
        logger.info("Worker %s started", self.worker_id)
        while True:
            if not self.run_once():
                self.sleeper(self.poll_seconds)


def default_worker_id() -> str:
    explicit = os.environ.get("LORCANA_WORKER_ID")
    if explicit and explicit.strip():
        return explicit.strip()
    return f"{socket.gethostname()}-{str(uuid4())[:8]}"


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    resources = ApplicationResources.from_env()
    try:
        lease_seconds = int(os.environ.get("LORCANA_JOB_LEASE_SECONDS", "900"))
        poll_seconds = float(os.environ.get("LORCANA_WORKER_POLL_SECONDS", "5"))
        queue = JobQueue.from_engine(resources.engine, lease_seconds=lease_seconds)
        worker = Worker(
            queue=queue,
            executor=PlatformJobExecutor(
                resources.engine,
                analyzer_registry=build_analyzer_registry(resources.settings),
            ),
            worker_id=default_worker_id(),
            poll_seconds=poll_seconds,
            scheduler=ScheduledJobService.from_engine(resources.engine),
        )
        worker.run_forever()
    finally:
        resources.close()


if __name__ == "__main__":  # pragma: no cover
    main()

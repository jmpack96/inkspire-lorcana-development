"""Typed records for durable background work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class EnqueuedJob:
    job_id: UUID
    created: bool


@dataclass(frozen=True)
class JobLease:
    job_id: UUID
    kind: str
    resource_key: str | None
    payload: dict[str, Any]
    attempt_number: int
    max_attempts: int
    lease_owner: str
    lease_token: UUID
    lease_expires_at: datetime


@dataclass(frozen=True)
class JobFailureResult:
    job_id: UUID
    status: str
    retry_at: datetime | None

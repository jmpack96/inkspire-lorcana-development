"""Durable PostgreSQL-backed background jobs and schedules."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from lorcana.db.metadata import metadata


jobs = Table(
    "jobs",
    metadata,
    Column("job_id", Uuid, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("resource_key", Text),
    Column("payload", JSONB, nullable=False),
    Column("idempotency_key", Text),
    Column("status", Text, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("lease_owner", Text),
    Column("lease_token", Uuid),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("progress", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("last_error_category", Text),
    Column("last_error_summary", Text),
    CheckConstraint(
        "status IN ('queued','running','succeeded','failed','cancelled')",
        name="jobs_status",
    ),
    CheckConstraint("attempt_count >= 0", name="jobs_attempt_count_nonnegative"),
    CheckConstraint("max_attempts >= 1", name="jobs_max_attempts_positive"),
    UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    Index("ix_jobs_claim", "status", "available_at", "priority"),
    Index("ix_jobs_kind", "kind"),
    Index("ix_jobs_resource_key", "resource_key"),
    Index("ix_jobs_lease_expires_at", "lease_expires_at"),
)


job_attempts = Table(
    "job_attempts",
    metadata,
    Column("job_id", Uuid, nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("lease_token", Uuid, nullable=False),
    Column("worker_id", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("status", Text, nullable=False),
    Column("error_category", Text),
    Column("error_summary", Text),
    PrimaryKeyConstraint("job_id", "attempt_number", name="pk_job_attempts"),
    UniqueConstraint("job_id", "lease_token", name="uq_job_attempts_job_lease"),
    CheckConstraint(
        "status IN ('running','succeeded','failed','lease_expired')",
        name="job_attempts_status",
    ),
)

# Define this FK after the Table declaration so naming remains explicit and
# Alembic output is stable.
from sqlalchemy import ForeignKeyConstraint  # noqa: E402
job_attempts.append_constraint(
    ForeignKeyConstraint(["job_id"], ["jobs.job_id"], name="fk_job_attempts_job_id_jobs")
)
Index("ix_job_attempts_worker", job_attempts.c.worker_id, job_attempts.c.started_at)


scheduled_jobs = Table(
    "scheduled_jobs",
    metadata,
    Column("scheduled_job_id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("resource_key", Text),
    Column("payload", JSONB, nullable=False),
    Column("schedule_spec", JSONB, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("next_run_at", DateTime(timezone=True), nullable=False),
    Column("last_enqueued_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("name", name="uq_scheduled_jobs_name"),
    Index("ix_scheduled_jobs_due", "enabled", "next_run_at"),
)

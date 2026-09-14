"""durable jobs and schedules

Revision ID: 20260913_0005
Revises: 20260913_0004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260913_0005"
down_revision: Union[str, Sequence[str], None] = "20260913_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("resource_key", sa.Text()),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_category", sa.Text()),
        sa.Column("last_error_summary", sa.Text()),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="jobs_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="jobs_attempt_count_nonnegative"),
        sa.CheckConstraint("max_attempts >= 1", name="jobs_max_attempts_positive"),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "available_at", "priority"])
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_resource_key", "jobs", ["resource_key"])
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])

    op.create_table(
        "job_attempts",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_category", sa.Text()),
        sa.Column("error_summary", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','lease_expired')",
            name="job_attempts_status",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], name="fk_job_attempts_job_id_jobs"),
        sa.PrimaryKeyConstraint("job_id", "attempt_number", name="pk_job_attempts"),
        sa.UniqueConstraint("job_id", "lease_token", name="uq_job_attempts_job_lease"),
    )
    op.create_index("ix_job_attempts_worker", "job_attempts", ["worker_id", "started_at"])

    op.create_table(
        "scheduled_jobs",
        sa.Column("scheduled_job_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("resource_key", sa.Text()),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schedule_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scheduled_job_id"),
        sa.UniqueConstraint("name", name="uq_scheduled_jobs_name"),
    )
    op.create_index("ix_scheduled_jobs_due", "scheduled_jobs", ["enabled", "next_run_at"])


def downgrade() -> None:
    op.drop_table("scheduled_jobs")
    op.drop_table("job_attempts")
    op.drop_table("jobs")

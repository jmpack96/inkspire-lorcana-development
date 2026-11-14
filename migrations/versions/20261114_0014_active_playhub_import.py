"""Keep at most one active Play Hub import per event."""

from alembic import op
import sqlalchemy as sa

revision = "20261114_0014"
down_revision = "20261011_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE jobs IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""
        CREATE TEMP TABLE duplicate_playhub_imports ON COMMIT DROP AS
        SELECT job_id
        FROM (
            SELECT job_id, row_number() OVER (
                PARTITION BY (payload->>'event_id')::bigint
                ORDER BY (status = 'running') DESC, priority DESC,
                         available_at, created_at, job_id
            ) AS position
            FROM jobs
            WHERE kind = 'playhub.import_event' AND status IN ('queued', 'running')
        ) AS ranked
        WHERE position > 1
    """)
    op.execute("""
        DELETE FROM job_attempts AS attempt
        USING duplicate_playhub_imports AS duplicate
        WHERE attempt.job_id = duplicate.job_id
    """)
    op.execute("""
        DELETE FROM jobs
        USING duplicate_playhub_imports AS duplicate
        WHERE jobs.job_id = duplicate.job_id
    """)
    op.execute("""
        UPDATE jobs
        SET resource_key = ((payload->>'event_id')::bigint)::text
        WHERE kind = 'playhub.import_event' AND status IN ('queued', 'running')
          AND resource_key IS DISTINCT FROM ((payload->>'event_id')::bigint)::text
    """)
    op.create_index(
        "uq_jobs_active_playhub_import",
        "jobs",
        ["resource_key"],
        unique=True,
        postgresql_where=sa.text(
            "kind = 'playhub.import_event' AND status IN ('queued', 'running')"
        ),
    )


def downgrade():
    op.drop_index("uq_jobs_active_playhub_import", table_name="jobs")

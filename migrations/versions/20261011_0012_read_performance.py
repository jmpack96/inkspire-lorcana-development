"""Bound query work with small partial indexes and hourly job cleanup."""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0012"
down_revision = "20261004_0011"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_jobs_queued_order": "ON jobs (priority DESC, available_at, created_at, job_id) WHERE status = 'queued'",
    "ix_jobs_running_expiry": "ON jobs (lease_expires_at) WHERE status = 'running'",
    "ix_jobs_terminal_cleanup": "ON jobs (completed_at, job_id) WHERE status IN ('succeeded','failed','cancelled')",
    "ix_duels_replays_summary": "ON duels_replays (connection_id, game_id, fetched_at DESC) WHERE status = 'valid'",
}


def upgrade():
    # Concurrent builds let imports and Discord reads continue during migration.
    # Drop first also makes retrying an interrupted/invalid index build safe.
    with op.get_context().autocommit_block():
        for name, definition in INDEXES.items():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            op.execute(f"CREATE INDEX CONCURRENTLY {name} {definition}")
    op.execute("UPDATE scheduled_jobs SET priority = 16, updated_at = now() "
               "WHERE name = 'maintenance-prune-jobs' AND kind = 'maintenance.prune_jobs' AND priority = 1")
    # Preserve customized schedules and retention settings.
    op.execute(sa.text("""
        UPDATE scheduled_jobs
        SET schedule_spec = jsonb_build_object('type', 'interval', 'seconds', 3600),
            updated_at = now()
        WHERE name = 'maintenance-prune-jobs'
          AND kind = 'maintenance.prune_jobs'
          AND schedule_spec = jsonb_build_object('type', 'daily', 'hour', 6, 'minute', 30, 'timezone', 'UTC')
    """))


def downgrade():
    op.execute("UPDATE scheduled_jobs SET priority = 1, updated_at = now() "
               "WHERE name = 'maintenance-prune-jobs' AND kind = 'maintenance.prune_jobs' AND priority = 16")
    op.execute(sa.text("""
        UPDATE scheduled_jobs
        SET schedule_spec = jsonb_build_object('type', 'daily', 'hour', 6, 'minute', 30, 'timezone', 'UTC'),
            updated_at = now()
        WHERE name = 'maintenance-prune-jobs'
          AND kind = 'maintenance.prune_jobs'
          AND schedule_spec = jsonb_build_object('type', 'interval', 'seconds', 3600)
    """))
    with op.get_context().autocommit_block():
        for name in reversed(INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")

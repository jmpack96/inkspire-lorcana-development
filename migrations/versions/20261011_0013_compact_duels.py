"""Compact Duels read data; backfill is deliberately outside the migration."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = "20261011_0013"
down_revision = "20261011_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("duels_read_models",
        sa.Column("normalization_id", sa.Uuid(), sa.ForeignKey("duels_normalizations.normalization_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("mulligan_count", sa.Integer()),
        sa.Column("decklist", JSONB()),
        sa.Column("opening_evidence", JSONB(), nullable=False),
        sa.CheckConstraint("mulligan_count IS NULL OR mulligan_count BETWEEN 0 AND 7", name="duels_read_models_mulligan_count"),
        if_not_exists=True)


def downgrade():
    op.drop_table("duels_read_models")

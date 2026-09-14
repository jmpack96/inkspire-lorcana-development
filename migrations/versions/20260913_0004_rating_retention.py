"""retain current and previous rating publication runs

Revision ID: 20260913_0004
Revises: 20260913_0003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260913_0004"
down_revision: Union[str, Sequence[str], None] = "20260913_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rating_publications",
        sa.Column("previous_rating_run_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_rating_publications_previous_rating_run_id_rating_runs",
        "rating_publications",
        "rating_runs",
        ["previous_rating_run_id"],
        ["rating_run_id"],
    )
    op.create_index(
        "ix_rating_publications_previous_run_id",
        "rating_publications",
        ["previous_rating_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rating_publications_previous_run_id", table_name="rating_publications")
    op.drop_constraint(
        "fk_rating_publications_previous_rating_run_id_rating_runs",
        "rating_publications",
        type_="foreignkey",
    )
    op.drop_column("rating_publications", "previous_rating_run_id")

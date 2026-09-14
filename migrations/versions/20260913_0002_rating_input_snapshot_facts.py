"""snapshot Elo calculation facts in rating_run_inputs

Revision ID: 20260913_0002
Revises: 20260913_0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260913_0002"
down_revision: Union[str, Sequence[str], None] = "20260913_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rating_run_inputs", sa.Column("player1_id", sa.BigInteger(), nullable=True))
    op.add_column("rating_run_inputs", sa.Column("player2_id", sa.BigInteger(), nullable=True))
    op.add_column("rating_run_inputs", sa.Column("winner_id", sa.BigInteger(), nullable=True))
    op.add_column("rating_run_inputs", sa.Column("is_draw", sa.Boolean(), nullable=True))

    # If a Phase 1 database was used experimentally before this migration, rebuild
    # every calculation/order fact from the referenced source rows before enforcing
    # an immutable complete snapshot. Invalid old experiments should fail migration
    # rather than become silently non-reproducible rating runs.
    op.execute("""
        UPDATE rating_run_inputs AS i
        SET
            player1_id = m.player1_id,
            player2_id = m.player2_id,
            winner_id = m.winner_id,
            is_draw = m.is_draw,
            event_start_datetime = COALESCE(i.event_start_datetime, e.start_datetime),
            phase_order = COALESCE(i.phase_order, p.phase_order, 0),
            round_number = COALESCE(i.round_number, r.round_number, 0)
        FROM playhub_matches AS m
        JOIN playhub_events AS e ON e.event_id = m.event_id
        LEFT JOIN playhub_rounds AS r ON r.round_id = m.round_id
        LEFT JOIN playhub_phases AS p ON p.phase_id = r.phase_id
        WHERE m.match_id = i.match_id
    """)
    op.alter_column("rating_run_inputs", "event_start_datetime", nullable=False)
    op.alter_column("rating_run_inputs", "phase_order", nullable=False)
    op.alter_column("rating_run_inputs", "round_number", nullable=False)
    op.alter_column("rating_run_inputs", "player1_id", nullable=False)
    op.alter_column("rating_run_inputs", "player2_id", nullable=False)
    op.alter_column("rating_run_inputs", "is_draw", nullable=False)

    op.create_foreign_key(
        "fk_rating_run_inputs_player1_id_playhub_players",
        "rating_run_inputs", "playhub_players", ["player1_id"], ["player_id"],
    )
    op.create_foreign_key(
        "fk_rating_run_inputs_player2_id_playhub_players",
        "rating_run_inputs", "playhub_players", ["player2_id"], ["player_id"],
    )
    op.create_foreign_key(
        "fk_rating_run_inputs_winner_id_playhub_players",
        "rating_run_inputs", "playhub_players", ["winner_id"], ["player_id"],
    )


def downgrade() -> None:
    op.alter_column("rating_run_inputs", "round_number", nullable=True)
    op.alter_column("rating_run_inputs", "phase_order", nullable=True)
    op.alter_column("rating_run_inputs", "event_start_datetime", nullable=True)
    op.drop_constraint("fk_rating_run_inputs_winner_id_playhub_players", "rating_run_inputs", type_="foreignkey")
    op.drop_constraint("fk_rating_run_inputs_player2_id_playhub_players", "rating_run_inputs", type_="foreignkey")
    op.drop_constraint("fk_rating_run_inputs_player1_id_playhub_players", "rating_run_inputs", type_="foreignkey")
    op.drop_column("rating_run_inputs", "is_draw")
    op.drop_column("rating_run_inputs", "winner_id")
    op.drop_column("rating_run_inputs", "player2_id")
    op.drop_column("rating_run_inputs", "player1_id")

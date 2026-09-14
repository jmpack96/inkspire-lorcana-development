from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text

from lorcana.db.schema.playhub import playhub_event_sync_state, playhub_events, playhub_matches
from lorcana.db.transfer_sqlite import SQLiteTransferError, transfer_sqlite_to_postgres, validate_sqlite_transfer
from support.legacy_sqlite import create_legacy_source

pytestmark = pytest.mark.integration


def _clear_foundation(db_engine) -> None:
    with db_engine.begin() as connection:
        connection.execute(text(
            "TRUNCATE TABLE "
            "rating_publications, rating_current, rating_history, rating_run_inputs, rating_runs, "
            "playhub_import_attempts, playhub_event_sync_state, playhub_discovery_runs, "
            "playhub_matches, playhub_registrations, playhub_rounds, playhub_phases, "
            "playhub_events, playhub_players, playhub_stores CASCADE"
        ))


def test_transfer_is_exact_validated_and_refuses_nonempty_target(db_engine, tmp_path: Path):
    _clear_foundation(db_engine)
    source = create_legacy_source(tmp_path / "legacy.db")

    try:
        report = transfer_sqlite_to_postgres(source, db_engine, batch_size=2)
        assert report.valid
        assert {result.table: result.target_rows for result in report.tables}["playhub_matches"] == 1

        with db_engine.connect() as connection:
            event = connection.execute(select(playhub_events).where(playhub_events.c.event_id == 100)).mappings().one()
            match = connection.execute(select(playhub_matches).where(playhub_matches.c.match_id == 500)).mappings().one()
            sync = connection.execute(
                select(playhub_event_sync_state).where(playhub_event_sync_state.c.event_id == 100)
            ).mappings().one()
        assert event["event_is_online"] is False
        assert match["is_draw"] is False
        assert sync["state"] == "complete"

        second_report = validate_sqlite_transfer(source, db_engine)
        assert second_report.valid
        assert second_report.source_sha256 == report.source_sha256

        with pytest.raises(SQLiteTransferError, match="not empty"):
            transfer_sqlite_to_postgres(source, db_engine, batch_size=2)
    finally:
        _clear_foundation(db_engine)

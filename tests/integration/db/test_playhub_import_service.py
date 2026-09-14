from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

from lorcana.db.schema.playhub import (
    playhub_event_sync_state,
    playhub_import_attempts,
    playhub_matches,
    playhub_registrations,
)
from lorcana.playhub.service import PlayHubImportService
from support.playhub_payloads import raw_event, raw_match, raw_standings

pytestmark = pytest.mark.integration


class FakeClient:
    def fetch_event_html(self, event_id):
        raise AssertionError("integration test supplies event_data")

    def fetch_all_standings(self, round_id):
        assert round_id == 101
        return raw_standings()

    def fetch_all_round_matches(self, round_id):
        assert round_id == 101
        return [raw_match()]


def _clear_foundation(db_engine) -> None:
    with db_engine.begin() as connection:
        connection.execute(text(
            "TRUNCATE TABLE "
            "rating_publications, rating_current, rating_history, rating_run_inputs, rating_runs, "
            "playhub_import_attempts, playhub_event_sync_state, playhub_discovery_runs, "
            "playhub_matches, playhub_registrations, playhub_rounds, playhub_phases, "
            "playhub_events, playhub_players, playhub_stores CASCADE"
        ))


def test_real_repository_import_is_idempotent_and_attempts_are_append_only(db_engine):
    _clear_foundation(db_engine)
    importer = PlayHubImportService.from_engine(db_engine, client=FakeClient())
    try:
        first = importer.import_event(1, event_data=raw_event())
        second = importer.import_event(1, event_data=raw_event())
        assert first.status == second.status == "complete"

        with db_engine.connect() as connection:
            assert connection.execute(select(func.count()).select_from(playhub_matches)).scalar_one() == 1
            assert connection.execute(select(func.count()).select_from(playhub_registrations)).scalar_one() == 2
            assert connection.execute(select(func.count()).select_from(playhub_import_attempts)).scalar_one() == 2
            sync = connection.execute(
                select(playhub_event_sync_state).where(playhub_event_sync_state.c.event_id == 1)
            ).mappings().one()
            assert sync["state"] == "complete"
            assert sync["last_success_at"] is not None
    finally:
        _clear_foundation(db_engine)

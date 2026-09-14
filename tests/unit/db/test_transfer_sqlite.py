from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lorcana.db.transfer_sqlite import (
    LegacySQLiteSource,
    SQLiteTransferError,
    _legacy_uuid,
    _specs,
    preflight_sqlite_source,
    sha256_file,
)


from support.legacy_sqlite import create_legacy_source


def test_preflight_checks_every_transform_and_never_changes_source(tmp_path):
    path = create_legacy_source(tmp_path / "legacy.db")
    before = sha256_file(path)

    digest, counts = preflight_sqlite_source(path)

    assert digest == before == sha256_file(path)
    assert counts == {
        "playhub_stores": 1,
        "playhub_players": 2,
        "playhub_events": 1,
        "playhub_phases": 1,
        "playhub_rounds": 1,
        "playhub_registrations": 1,
        "playhub_matches": 1,
        "playhub_discovery_runs": 1,
        "playhub_import_attempts": 1,
        "playhub_event_sync_state": 1,
    }


def test_workflow_state_is_split_from_event_source_facts(tmp_path):
    path = create_legacy_source(tmp_path / "legacy.db", event_results_status="FAILED")
    specs = {spec.target_name: spec for spec in _specs()}

    with LegacySQLiteSource(path) as source:
        source.preflight()
        event = next(source.rows(specs["playhub_events"]))
        sync = next(source.rows(specs["playhub_event_sync_state"]))
        attempt = next(source.rows(specs["playhub_import_attempts"]))

    assert "results_status" not in event
    assert event["event_is_online"] is False
    assert sync["state"] == "failed"
    assert sync["last_error_summary"] == "boom"
    assert attempt["status"] == "failed"
    assert attempt["started_at"] == attempt["completed_at"]


def test_legacy_internal_uuid_mapping_is_deterministic_and_namespaced():
    first = _legacy_uuid("import_attempt", 7)
    assert first == _legacy_uuid("import_attempt", 7)
    assert first != _legacy_uuid("import_attempt", 8)
    assert first != _legacy_uuid("discovery_run", 7)


def test_preflight_rejects_naive_legacy_timestamps(tmp_path):
    path = create_legacy_source(tmp_path / "legacy.db")
    connection = sqlite3.connect(path)
    connection.execute("UPDATE players SET first_seen = '2026-09-13T20:00:00' WHERE player_id = 1")
    connection.commit()
    connection.close()

    with pytest.raises(SQLiteTransferError, match="Naive timestamp"):
        preflight_sqlite_source(path)


def test_source_connection_is_query_only(tmp_path):
    path = create_legacy_source(tmp_path / "legacy.db")
    with LegacySQLiteSource(path) as source:
        with pytest.raises(sqlite3.OperationalError):
            source.connection.execute("DELETE FROM matches")

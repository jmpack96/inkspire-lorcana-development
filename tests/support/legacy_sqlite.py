from __future__ import annotations

import sqlite3
from pathlib import Path

LEGACY_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE stores (
    store_id TEXT PRIMARY KEY, name TEXT NOT NULL, full_address TEXT, city TEXT,
    state_region TEXT, country TEXT, latitude REAL, longitude REAL, email TEXT,
    website TEXT, first_seen TEXT, last_seen TEXT, last_synced TEXT
);
CREATE TABLE events (
    event_id INTEGER PRIMARY KEY, store_id TEXT, name TEXT NOT NULL,
    start_datetime TEXT, end_datetime TEXT, timezone TEXT, gameplay_format_id TEXT,
    format TEXT, event_format TEXT, category TEXT, display_status TEXT, event_status TEXT,
    lifecycle_status TEXT, player_count INTEGER, registered_user_count INTEGER, capacity INTEGER,
    event_is_online INTEGER, full_address TEXT, latitude REAL, longitude REAL, source_url TEXT,
    discovered_at TEXT, last_synced TEXT, results_status TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED',
    results_last_attempted TEXT, results_last_success TEXT,
    FOREIGN KEY (store_id) REFERENCES stores(store_id)
);
CREATE TABLE phases (
    phase_id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, phase_name TEXT, phase_order INTEGER,
    round_type TEXT, status TEXT, FOREIGN KEY(event_id) REFERENCES events(event_id)
);
CREATE TABLE rounds (
    round_id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, phase_id INTEGER, round_number INTEGER,
    round_type TEXT, status TEXT, pairings_status TEXT, standings_status TEXT,
    final_round_in_event INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(event_id) REFERENCES events(event_id), FOREIGN KEY(phase_id) REFERENCES phases(phase_id)
);
CREATE TABLE players (
    player_id INTEGER PRIMARY KEY, display_name TEXT, username TEXT, first_seen TEXT, last_seen TEXT
);
CREATE TABLE registrations (
    registration_id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, player_id INTEGER NOT NULL,
    display_name_at_event TEXT, registration_status TEXT, matches_won INTEGER, matches_lost INTEGER,
    matches_drawn INTEGER, match_points INTEGER, placement INTEGER, registered_at TEXT, last_synced TEXT,
    FOREIGN KEY(event_id) REFERENCES events(event_id), FOREIGN KEY(player_id) REFERENCES players(player_id)
);
CREATE TABLE matches (
    match_id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, round_id INTEGER NOT NULL,
    player1_id INTEGER, player2_id INTEGER, participant_count INTEGER, player1_score INTEGER,
    player2_score INTEGER, winner_id INTEGER, status TEXT, table_number INTEGER,
    is_draw INTEGER NOT NULL DEFAULT 0, is_intentional_draw INTEGER NOT NULL DEFAULT 0,
    is_unintentional_draw INTEGER NOT NULL DEFAULT 0, is_bye INTEGER NOT NULL DEFAULT 0,
    is_loss INTEGER NOT NULL DEFAULT 0, is_ghost_match INTEGER NOT NULL DEFAULT 0,
    is_feature_match INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT,
    FOREIGN KEY(event_id) REFERENCES events(event_id), FOREIGN KEY(round_id) REFERENCES rounds(round_id),
    FOREIGN KEY(player1_id) REFERENCES players(player_id), FOREIGN KEY(player2_id) REFERENCES players(player_id),
    FOREIGN KEY(winner_id) REFERENCES players(player_id)
);
CREATE TABLE discovery_runs (
    discovery_run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, completed_at TEXT,
    start_datetime TEXT NOT NULL, end_datetime TEXT NOT NULL, events_received INTEGER NOT NULL DEFAULT 0,
    unique_events INTEGER NOT NULL DEFAULT 0, duplicate_rows INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL, error TEXT
);
CREATE TABLE import_log (
    import_log_id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, imported_at TEXT NOT NULL,
    rounds_expected INTEGER, rounds_imported INTEGER, registrations_found INTEGER, matches_found INTEGER,
    players_found INTEGER, status TEXT NOT NULL, error TEXT,
    FOREIGN KEY(event_id) REFERENCES events(event_id)
);
"""

UTC = "2026-09-13T20:00:00+00:00"


def create_legacy_source(path: Path, *, event_results_status: str = "SUCCESS") -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(LEGACY_SCHEMA)
    connection.execute(
        "INSERT INTO stores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("store-1", "Store", "1 Main", "Reston", "VA", "US", 1.5, 2.5, None, None, UTC, UTC, UTC),
    )
    connection.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            100, "store-1", "Event", UTC, UTC, "UTC", "core", "CORE", "SWISS", "SET_CHAMP",
            "PUBLIC", "SCHEDULED", "ACTIVE", 2, 2, 32, 0, "1 Main", 1.5, 2.5,
            "https://example.test/event/100", UTC, UTC, event_results_status, UTC,
            UTC if event_results_status == "SUCCESS" else None,
        ),
    )
    connection.execute("INSERT INTO phases VALUES (?,?,?,?,?,?)", (200, 100, "Swiss", 1, "SWISS", "COMPLETE"))
    connection.execute(
        "INSERT INTO rounds VALUES (?,?,?,?,?,?,?,?,?)",
        (300, 100, 200, 1, "SWISS", "COMPLETE", "COMPLETE", "COMPLETE", 1),
    )
    connection.executemany(
        "INSERT INTO players VALUES (?,?,?,?,?)",
        [(1, "Player One", "one", UTC, UTC), (2, "Player Two", "two", UTC, UTC)],
    )
    connection.execute(
        "INSERT INTO registrations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (400, 100, 1, "Player One", "ACTIVE", 1, 0, 0, 3, 1, None, UTC),
    )
    connection.execute(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (500, 100, 300, 1, 2, 2, 2, 0, 1, "COMPLETE", 1, 0, 0, 0, 0, 0, 0, 0, UTC, UTC),
    )
    # Legacy discovery windows were deliberately date-only and interpreted as UTC midnight.
    connection.execute(
        "INSERT INTO discovery_runs(started_at,completed_at,start_datetime,end_datetime,events_received,unique_events,duplicate_rows,status,error) VALUES (?,?,?,?,?,?,?,?,?)",
        (UTC, UTC, "2026-09-13", "2026-09-14", 1, 1, 0, "SUCCESS", None),
    )
    import_status = "SUCCESS" if event_results_status == "SUCCESS" else "FAILED"
    connection.execute(
        "INSERT INTO import_log(event_id,imported_at,rounds_expected,rounds_imported,registrations_found,matches_found,players_found,status,error) VALUES (?,?,?,?,?,?,?,?,?)",
        (100, UTC, 1, 1, 1, 1, 2, import_status, None if import_status == "SUCCESS" else "boom"),
    )
    connection.commit()
    connection.close()
    return path

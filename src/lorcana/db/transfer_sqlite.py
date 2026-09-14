"""One-way, read-only transfer from the frozen legacy SQLite database to PostgreSQL.

This module intentionally does not support SQLite as a runtime backend.  It exists only
for the controlled historical cutover described in the platform architecture.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Select, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.schema import Table

from lorcana.db.schema.playhub import (
    playhub_discovery_runs,
    playhub_event_sync_state,
    playhub_events,
    playhub_import_attempts,
    playhub_matches,
    playhub_phases,
    playhub_players,
    playhub_registrations,
    playhub_rounds,
    playhub_stores,
)
from lorcana.errors import LorcanaError

# Fixed forever once Phase 2 ships.  These UUIDs give legacy internal rows stable IDs
# without pretending their old SQLite AUTOINCREMENT values were Play Hub source IDs.
LEGACY_TRANSFER_NAMESPACE = UUID("d3a34b79-fca2-5aa0-989a-13cd2be7fbe0")


class SQLiteTransferError(LorcanaError):
    """The frozen source or target does not satisfy transfer safety requirements."""


@dataclass(frozen=True)
class TableTransferResult:
    table: str
    source_rows: int
    target_rows: int
    source_digest: str
    target_digest: str

    @property
    def valid(self) -> bool:
        return self.source_rows == self.target_rows and self.source_digest == self.target_digest


@dataclass(frozen=True)
class TransferReport:
    source_path: Path
    source_sha256: str
    tables: tuple[TableTransferResult, ...]
    foreign_key_violations: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return all(table.valid for table in self.tables) and not self.foreign_key_violations

    @property
    def source_rows(self) -> int:
        return sum(table.source_rows for table in self.tables)


@dataclass(frozen=True)
class _TransferSpec:
    source_name: str
    target: Table
    query: str
    transform: Callable[[sqlite3.Row], dict[str, Any]]

    @property
    def target_name(self) -> str:
        return self.target.name

    @property
    def target_columns(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.target.columns)


EXPECTED_SOURCE_COLUMNS: dict[str, set[str]] = {
    "stores": {
        "store_id", "name", "full_address", "city", "state_region", "country",
        "latitude", "longitude", "email", "website", "first_seen", "last_seen", "last_synced",
    },
    "events": {
        "event_id", "store_id", "name", "start_datetime", "end_datetime", "timezone",
        "gameplay_format_id", "format", "event_format", "category", "display_status",
        "event_status", "lifecycle_status", "player_count", "registered_user_count", "capacity",
        "event_is_online", "full_address", "latitude", "longitude", "source_url", "discovered_at",
        "last_synced", "results_status", "results_last_attempted", "results_last_success",
    },
    "phases": {"phase_id", "event_id", "phase_name", "phase_order", "round_type", "status"},
    "rounds": {
        "round_id", "event_id", "phase_id", "round_number", "round_type", "status",
        "pairings_status", "standings_status", "final_round_in_event",
    },
    "players": {"player_id", "display_name", "username", "first_seen", "last_seen"},
    "registrations": {
        "registration_id", "event_id", "player_id", "display_name_at_event", "registration_status",
        "matches_won", "matches_lost", "matches_drawn", "match_points", "placement", "registered_at",
        "last_synced",
    },
    "matches": {
        "match_id", "event_id", "round_id", "player1_id", "player2_id", "participant_count",
        "player1_score", "player2_score", "winner_id", "status", "table_number", "is_draw",
        "is_intentional_draw", "is_unintentional_draw", "is_bye", "is_loss", "is_ghost_match",
        "is_feature_match", "created_at", "updated_at",
    },
    "discovery_runs": {
        "discovery_run_id", "started_at", "completed_at", "start_datetime", "end_datetime",
        "events_received", "unique_events", "duplicate_rows", "status", "error",
    },
    "import_log": {
        "import_log_id", "event_id", "imported_at", "rounds_expected", "rounds_imported",
        "registrations_found", "matches_found", "players_found", "status", "error",
    },
}


TRANSFER_TARGETS: tuple[Table, ...] = (
    playhub_stores,
    playhub_players,
    playhub_events,
    playhub_phases,
    playhub_rounds,
    playhub_registrations,
    playhub_matches,
    playhub_discovery_runs,
    playhub_import_attempts,
    playhub_event_sync_state,
)


_TIMESTAMP_FIELDS = {
    "first_seen", "last_seen", "last_synced", "start_datetime", "end_datetime",
    "discovered_at", "registered_at", "created_at", "updated_at", "started_at",
    "completed_at", "last_attempt_at", "last_success_at",
}


def sha256_file(path: Path, *, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def _parse_timestamp(value: Any, *, field: str, key: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise SQLiteTransferError(f"Invalid timestamp in {field} for source key {key!r}") from error
    else:
        raise SQLiteTransferError(f"Unexpected timestamp type in {field} for source key {key!r}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SQLiteTransferError(f"Naive timestamp in {field} for source key {key!r}")
    return parsed.astimezone(timezone.utc)




def _parse_discovery_boundary(value: Any, *, field: str, key: Any) -> datetime:
    """Interpret legacy discovery date windows exactly as the old importer did.

    The legacy discovery code intentionally stored date-only boundaries (YYYY-MM-DD) and
    interpreted them as UTC midnight before calling Play Hub.  That behavior is therefore
    source semantics, not a migration-time timezone guess.
    """
    if isinstance(value, str) and len(value) == 10:
        try:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        except ValueError as error:
            raise SQLiteTransferError(f"Invalid discovery boundary in {field} for source key {key!r}") from error
    parsed = _parse_timestamp(value, field=field, key=key)
    if parsed is None:
        raise SQLiteTransferError(f"Missing discovery boundary in {field} for source key {key!r}")
    return parsed

def _parse_bool(value: Any, *, field: str, key: Any, nullable: bool = False) -> bool | None:
    if value is None and nullable:
        return None
    if value in (0, False):
        return False
    if value in (1, True):
        return True
    raise SQLiteTransferError(f"Invalid legacy boolean {value!r} in {field} for source key {key!r}")


def _legacy_uuid(kind: str, legacy_id: int) -> UUID:
    return uuid5(LEGACY_TRANSFER_NAMESPACE, f"{kind}:{legacy_id}")


def _normalize_import_status(value: str, *, key: Any) -> str:
    mapping = {
        "SUCCESS": "complete",
        "FAILED": "failed",
        "NO_RESULTS": "no_results",
        "PARTIAL": "partial",
    }
    try:
        return mapping[value]
    except KeyError as error:
        raise SQLiteTransferError(f"Unknown import status {value!r} for source key {key!r}") from error


def _normalize_discovery_status(value: str, *, key: Any) -> str:
    mapping = {"SUCCESS": "complete", "FAILED": "failed"}
    try:
        return mapping[value]
    except KeyError as error:
        raise SQLiteTransferError(f"Unknown discovery status {value!r} for source key {key!r}") from error


def _normalize_sync_state(value: str, *, key: Any) -> str:
    mapping = {
        "NOT_ATTEMPTED": "pending",
        "SUCCESS": "complete",
        "FAILED": "failed",
        "NO_RESULTS": "no_results",
        "PARTIAL": "partial",
    }
    try:
        return mapping[value]
    except KeyError as error:
        raise SQLiteTransferError(f"Unknown event results status {value!r} for source key {key!r}") from error


def _transform_store(row: sqlite3.Row) -> dict[str, Any]:
    key = row["store_id"]
    return {
        "store_id": key,
        "name": row["name"],
        "full_address": row["full_address"],
        "city": row["city"],
        "state_region": row["state_region"],
        "country": row["country"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "email": row["email"],
        "website": row["website"],
        "first_seen": _parse_timestamp(row["first_seen"], field="stores.first_seen", key=key),
        "last_seen": _parse_timestamp(row["last_seen"], field="stores.last_seen", key=key),
        "last_synced": _parse_timestamp(row["last_synced"], field="stores.last_synced", key=key),
    }


def _transform_player(row: sqlite3.Row) -> dict[str, Any]:
    key = row["player_id"]
    return {
        "player_id": key,
        "display_name": row["display_name"],
        "username": row["username"],
        "first_seen": _parse_timestamp(row["first_seen"], field="players.first_seen", key=key),
        "last_seen": _parse_timestamp(row["last_seen"], field="players.last_seen", key=key),
    }


def _transform_event(row: sqlite3.Row) -> dict[str, Any]:
    key = row["event_id"]
    return {
        "event_id": key,
        "store_id": row["store_id"],
        "name": row["name"],
        "start_datetime": _parse_timestamp(row["start_datetime"], field="events.start_datetime", key=key),
        "end_datetime": _parse_timestamp(row["end_datetime"], field="events.end_datetime", key=key),
        "timezone": row["timezone"],
        "gameplay_format_id": row["gameplay_format_id"],
        "format": row["format"],
        "event_format": row["event_format"],
        "category": row["category"],
        "display_status": row["display_status"],
        "event_status": row["event_status"],
        "lifecycle_status": row["lifecycle_status"],
        "player_count": row["player_count"],
        "registered_user_count": row["registered_user_count"],
        "capacity": row["capacity"],
        "event_is_online": _parse_bool(row["event_is_online"], field="events.event_is_online", key=key, nullable=True),
        "full_address": row["full_address"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "source_url": row["source_url"],
        "discovered_at": _parse_timestamp(row["discovered_at"], field="events.discovered_at", key=key),
        "last_synced": _parse_timestamp(row["last_synced"], field="events.last_synced", key=key),
    }


def _transform_phase(row: sqlite3.Row) -> dict[str, Any]:
    return {column: row[column] for column in ("phase_id", "event_id", "phase_name", "phase_order", "round_type", "status")}


def _transform_round(row: sqlite3.Row) -> dict[str, Any]:
    key = row["round_id"]
    return {
        "round_id": key,
        "event_id": row["event_id"],
        "phase_id": row["phase_id"],
        "round_number": row["round_number"],
        "round_type": row["round_type"],
        "status": row["status"],
        "pairings_status": row["pairings_status"],
        "standings_status": row["standings_status"],
        "final_round_in_event": _parse_bool(
            row["final_round_in_event"], field="rounds.final_round_in_event", key=key
        ),
    }


def _transform_registration(row: sqlite3.Row) -> dict[str, Any]:
    key = row["registration_id"]
    return {
        "registration_id": key,
        "event_id": row["event_id"],
        "player_id": row["player_id"],
        "display_name_at_event": row["display_name_at_event"],
        "registration_status": row["registration_status"],
        "matches_won": row["matches_won"],
        "matches_lost": row["matches_lost"],
        "matches_drawn": row["matches_drawn"],
        "match_points": row["match_points"],
        "placement": row["placement"],
        "registered_at": _parse_timestamp(row["registered_at"], field="registrations.registered_at", key=key),
        "last_synced": _parse_timestamp(row["last_synced"], field="registrations.last_synced", key=key),
    }


def _transform_match(row: sqlite3.Row) -> dict[str, Any]:
    key = row["match_id"]
    result = {
        column: row[column]
        for column in (
            "match_id", "event_id", "round_id", "player1_id", "player2_id", "participant_count",
            "player1_score", "player2_score", "winner_id", "status", "table_number",
        )
    }
    for field in (
        "is_draw", "is_intentional_draw", "is_unintentional_draw", "is_bye", "is_loss",
        "is_ghost_match", "is_feature_match",
    ):
        result[field] = _parse_bool(row[field], field=f"matches.{field}", key=key)
    result["created_at"] = _parse_timestamp(row["created_at"], field="matches.created_at", key=key)
    result["updated_at"] = _parse_timestamp(row["updated_at"], field="matches.updated_at", key=key)
    return result


def _transform_discovery_run(row: sqlite3.Row) -> dict[str, Any]:
    key = row["discovery_run_id"]
    error_summary = row["error"]
    return {
        "discovery_run_id": _legacy_uuid("discovery_run", key),
        "started_at": _parse_timestamp(row["started_at"], field="discovery_runs.started_at", key=key),
        "completed_at": _parse_timestamp(row["completed_at"], field="discovery_runs.completed_at", key=key),
        "start_datetime": _parse_discovery_boundary(
            row["start_datetime"], field="discovery_runs.start_datetime", key=key
        ),
        "end_datetime": _parse_discovery_boundary(
            row["end_datetime"], field="discovery_runs.end_datetime", key=key
        ),
        "events_received": row["events_received"],
        "unique_events": row["unique_events"],
        "duplicate_rows": row["duplicate_rows"],
        "status": _normalize_discovery_status(row["status"], key=key),
        "error_category": "legacy_discovery_error" if error_summary else None,
        "error_summary": error_summary,
    }


def _transform_import_attempt(row: sqlite3.Row) -> dict[str, Any]:
    key = row["import_log_id"]
    imported_at = _parse_timestamp(row["imported_at"], field="import_log.imported_at", key=key)
    error_summary = row["error"]
    return {
        "import_attempt_id": _legacy_uuid("import_attempt", key),
        "event_id": row["event_id"],
        "job_id": None,
        # Legacy import_log had a single completion timestamp.  Preserve it in both fields
        # rather than inventing a start time.
        "started_at": imported_at,
        "completed_at": imported_at,
        "status": _normalize_import_status(row["status"], key=key),
        "rounds_expected": row["rounds_expected"],
        "rounds_imported": row["rounds_imported"],
        "registrations_found": row["registrations_found"],
        "matches_found": row["matches_found"],
        "players_found": row["players_found"],
        "error_category": "legacy_import_error" if error_summary else None,
        "error_summary": error_summary,
    }


def _transform_event_sync_state(row: sqlite3.Row) -> dict[str, Any]:
    key = row["event_id"]
    state = _normalize_sync_state(row["results_status"], key=key)
    latest_error = row["latest_error"] if state == "failed" else None
    return {
        "event_id": key,
        "state": state,
        "last_attempt_at": _parse_timestamp(
            row["results_last_attempted"], field="events.results_last_attempted", key=key
        ),
        "last_success_at": _parse_timestamp(
            row["results_last_success"], field="events.results_last_success", key=key
        ),
        "last_error_category": "legacy_import_error" if latest_error else None,
        "last_error_summary": latest_error,
        "source_revision": None,
    }


def _specs() -> tuple[_TransferSpec, ...]:
    return (
        _TransferSpec("stores", playhub_stores, "SELECT * FROM stores ORDER BY store_id", _transform_store),
        _TransferSpec("players", playhub_players, "SELECT * FROM players ORDER BY player_id", _transform_player),
        _TransferSpec("events", playhub_events, "SELECT * FROM events ORDER BY event_id", _transform_event),
        _TransferSpec("phases", playhub_phases, "SELECT * FROM phases ORDER BY phase_id", _transform_phase),
        _TransferSpec("rounds", playhub_rounds, "SELECT * FROM rounds ORDER BY round_id", _transform_round),
        _TransferSpec(
            "registrations", playhub_registrations,
            "SELECT * FROM registrations ORDER BY registration_id", _transform_registration,
        ),
        _TransferSpec("matches", playhub_matches, "SELECT * FROM matches ORDER BY match_id", _transform_match),
        _TransferSpec(
            "discovery_runs", playhub_discovery_runs,
            "SELECT * FROM discovery_runs ORDER BY discovery_run_id", _transform_discovery_run,
        ),
        _TransferSpec(
            "import_log", playhub_import_attempts,
            "SELECT * FROM import_log ORDER BY import_log_id", _transform_import_attempt,
        ),
        _TransferSpec(
            "events", playhub_event_sync_state,
            """
            SELECT
                e.event_id,
                e.results_status,
                e.results_last_attempted,
                e.results_last_success,
                latest.error AS latest_error
            FROM events AS e
            LEFT JOIN (
                SELECT il.event_id, il.error
                FROM import_log AS il
                INNER JOIN (
                    SELECT event_id, MAX(import_log_id) AS import_log_id
                    FROM import_log
                    GROUP BY event_id
                ) AS newest
                    ON newest.import_log_id = il.import_log_id
            ) AS latest
                ON latest.event_id = e.event_id
            ORDER BY e.event_id
            """,
            _transform_event_sync_state,
        ),
    )


class LegacySQLiteSource:
    """Read-only access to the exact legacy source schema."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> "LegacySQLiteSource":
        if not self.path.is_file():
            raise SQLiteTransferError(f"SQLite source does not exist: {self.path}")
        uri = self.path.as_uri() + "?mode=ro&immutable=1"
        try:
            connection = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as error:
            raise SQLiteTransferError(f"Could not open SQLite source read-only: {self.path}") from error
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        self._connection = connection
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("LegacySQLiteSource must be used as a context manager")
        return self._connection

    def preflight(self) -> None:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise SQLiteTransferError(f"SQLite integrity_check failed: {integrity!r}")
        foreign_key_problem = self.connection.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_problem is not None:
            raise SQLiteTransferError(f"SQLite foreign_key_check failed: {tuple(foreign_key_problem)!r}")

        actual_tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing_tables = sorted(set(EXPECTED_SOURCE_COLUMNS) - actual_tables)
        if missing_tables:
            raise SQLiteTransferError(f"SQLite source is missing required tables: {', '.join(missing_tables)}")

        for table, expected_columns in EXPECTED_SOURCE_COLUMNS.items():
            actual_columns = {row[1] for row in self.connection.execute(f'PRAGMA table_info("{table}")')}
            missing_columns = sorted(expected_columns - actual_columns)
            if missing_columns:
                raise SQLiteTransferError(
                    f"SQLite table {table} is missing required columns: {', '.join(missing_columns)}"
                )

    def rows(self, spec: _TransferSpec) -> Iterator[dict[str, Any]]:
        try:
            cursor = self.connection.execute(spec.query)
            for row in cursor:
                yield spec.transform(row)
        except sqlite3.Error as error:
            raise SQLiteTransferError(f"Failed reading legacy SQLite table {spec.source_name}") from error

    def source_counts(self) -> dict[str, int]:
        return {
            table: self.connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in EXPECTED_SOURCE_COLUMNS
        }


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise SQLiteTransferError("Target returned a naive timestamp during validation")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, UUID):
        return str(value)
    return value


def _row_bytes(row: Mapping[str, Any], columns: Sequence[str]) -> bytes:
    values = [_canonical_value(row[column]) for column in columns]
    return (json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


class _DigestCounter:
    """Order-independent digest of a table's canonical transformed rows.

    SQLite and PostgreSQL can use different text/UUID sort orders, so validation must
    not depend on database collation.  Each row is hashed independently; those fixed
    width hashes are sorted in Python and then hashed as a multiset.  Row count plus
    primary/unique constraints preserve duplicate sensitivity where it matters.
    """

    def __init__(self, columns: Sequence[str]):
        self.columns = tuple(columns)
        self.rows = 0
        self._row_hashes: list[bytes] = []

    def add(self, row: Mapping[str, Any]) -> None:
        self._row_hashes.append(hashlib.sha256(_row_bytes(row, self.columns)).digest())
        self.rows += 1

    @property
    def hexdigest(self) -> str:
        digest = hashlib.sha256()
        for row_hash in sorted(self._row_hashes):
            digest.update(row_hash)
        return digest.hexdigest()


def _target_digest(connection: Connection, table: Table) -> tuple[int, str]:
    primary_key = tuple(table.primary_key.columns)
    if not primary_key:
        raise SQLiteTransferError(f"Target table {table.name} has no primary key for deterministic validation")
    statement: Select[Any] = select(*table.columns).order_by(*primary_key)
    counter = _DigestCounter(tuple(column.name for column in table.columns))
    streaming_connection = connection.execution_options(stream_results=True)
    for row in streaming_connection.execute(statement).mappings():
        counter.add(row)
    return counter.rows, counter.hexdigest


def _ensure_target_schema(connection: Connection) -> None:
    available = set(inspect(connection).get_table_names())
    required = {table.name for table in TRANSFER_TARGETS}
    missing = sorted(required - available)
    if missing:
        raise SQLiteTransferError(
            "PostgreSQL target is missing migrated Phase 1 tables: " + ", ".join(missing)
        )


def _ensure_empty_target(connection: Connection) -> None:
    nonempty: list[str] = []
    for table in TRANSFER_TARGETS:
        count = connection.execute(select(func.count()).select_from(table)).scalar_one()
        if count:
            nonempty.append(f"{table.name}={count}")
    if nonempty:
        raise SQLiteTransferError(
            "Refusing transfer because target Play Hub tables are not empty: " + ", ".join(nonempty)
        )


def _foreign_key_violations(connection: Connection) -> tuple[str, ...]:
    checks = {
        "events.store_id": """
            SELECT count(*) FROM playhub_events e
            LEFT JOIN playhub_stores s ON s.store_id = e.store_id
            WHERE e.store_id IS NOT NULL AND s.store_id IS NULL
        """,
        "phases.event_id": """
            SELECT count(*) FROM playhub_phases p
            LEFT JOIN playhub_events e ON e.event_id = p.event_id
            WHERE e.event_id IS NULL
        """,
        "rounds.event_id": """
            SELECT count(*) FROM playhub_rounds r
            LEFT JOIN playhub_events e ON e.event_id = r.event_id
            WHERE e.event_id IS NULL
        """,
        "rounds.phase_id": """
            SELECT count(*) FROM playhub_rounds r
            LEFT JOIN playhub_phases p ON p.phase_id = r.phase_id
            WHERE r.phase_id IS NOT NULL AND p.phase_id IS NULL
        """,
        "registrations.event_id": """
            SELECT count(*) FROM playhub_registrations r
            LEFT JOIN playhub_events e ON e.event_id = r.event_id
            WHERE e.event_id IS NULL
        """,
        "registrations.player_id": """
            SELECT count(*) FROM playhub_registrations r
            LEFT JOIN playhub_players p ON p.player_id = r.player_id
            WHERE p.player_id IS NULL
        """,
        "matches.event_id": """
            SELECT count(*) FROM playhub_matches m
            LEFT JOIN playhub_events e ON e.event_id = m.event_id
            WHERE e.event_id IS NULL
        """,
        "matches.round_id": """
            SELECT count(*) FROM playhub_matches m
            LEFT JOIN playhub_rounds r ON r.round_id = m.round_id
            WHERE r.round_id IS NULL
        """,
        "matches.player1_id": """
            SELECT count(*) FROM playhub_matches m
            LEFT JOIN playhub_players p ON p.player_id = m.player1_id
            WHERE m.player1_id IS NOT NULL AND p.player_id IS NULL
        """,
        "matches.player2_id": """
            SELECT count(*) FROM playhub_matches m
            LEFT JOIN playhub_players p ON p.player_id = m.player2_id
            WHERE m.player2_id IS NOT NULL AND p.player_id IS NULL
        """,
        "matches.winner_id": """
            SELECT count(*) FROM playhub_matches m
            LEFT JOIN playhub_players p ON p.player_id = m.winner_id
            WHERE m.winner_id IS NOT NULL AND p.player_id IS NULL
        """,
        "sync_state.event_id": """
            SELECT count(*) FROM playhub_event_sync_state s
            LEFT JOIN playhub_events e ON e.event_id = s.event_id
            WHERE e.event_id IS NULL
        """,
        "import_attempts.event_id": """
            SELECT count(*) FROM playhub_import_attempts i
            LEFT JOIN playhub_events e ON e.event_id = i.event_id
            WHERE e.event_id IS NULL
        """,
    }
    violations: list[str] = []
    for relationship, query in checks.items():
        count = connection.execute(text(query)).scalar_one()
        if count:
            violations.append(f"{relationship}: {count} orphan rows")
    return tuple(violations)


def _validate_against_expected(
    connection: Connection,
    expected: Mapping[str, tuple[int, str]],
) -> tuple[TableTransferResult, ...]:
    results: list[TableTransferResult] = []
    for table in TRANSFER_TARGETS:
        target_rows, target_digest = _target_digest(connection, table)
        source_rows, source_digest = expected[table.name]
        result = TableTransferResult(
            table=table.name,
            source_rows=source_rows,
            target_rows=target_rows,
            source_digest=source_digest,
            target_digest=target_digest,
        )
        results.append(result)
        if not result.valid:
            raise SQLiteTransferError(
                f"Validation failed for {table.name}: source rows/digest "
                f"{source_rows}/{source_digest} != target {target_rows}/{target_digest}"
            )
    return tuple(results)


def _expected_from_source(source: LegacySQLiteSource) -> dict[str, tuple[int, str]]:
    expected: dict[str, tuple[int, str]] = {}
    for spec in _specs():
        counter = _DigestCounter(spec.target_columns)
        for row in source.rows(spec):
            counter.add(row)
        expected[spec.target_name] = (counter.rows, counter.hexdigest)
    return expected


def preflight_sqlite_source(source_path: str | Path) -> tuple[str, dict[str, int]]:
    """Validate the frozen source without requiring PostgreSQL."""
    path = Path(source_path).expanduser().resolve()
    before = sha256_file(path)
    with LegacySQLiteSource(path) as source:
        source.preflight()
        # Execute every transform so malformed timestamps/booleans/statuses fail now,
        # not halfway through a PostgreSQL transfer.
        counts: dict[str, int] = {}
        for spec in _specs():
            count = 0
            for _ in source.rows(spec):
                count += 1
            counts[spec.target_name] = count
    after = sha256_file(path)
    if before != after:
        raise SQLiteTransferError("SQLite source checksum changed during preflight")
    return before, counts


def transfer_sqlite_to_postgres(
    source_path: str | Path,
    engine: Engine,
    *,
    batch_size: int = 5_000,
    progress: Callable[[str], None] | None = None,
) -> TransferReport:
    """Atomically transfer and validate a frozen legacy SQLite database.

    Safety properties:
    - SQLite is opened immutable/read-only and never written.
    - The PostgreSQL target must already be migrated and its Play Hub tables empty.
    - No target rows are committed until row digests and FK checks pass.
    - The source file hash must be unchanged at the end of validation.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    say = progress or (lambda _message: None)
    path = Path(source_path).expanduser().resolve()
    source_sha256 = sha256_file(path)
    say(f"Source SHA-256: {source_sha256}")

    with LegacySQLiteSource(path) as source:
        source.preflight()
        say("SQLite integrity, schema, and foreign keys: OK")

        with engine.begin() as connection:
            _ensure_target_schema(connection)
            _ensure_empty_target(connection)
            say("PostgreSQL target schema present and transfer tables empty")

            expected: dict[str, tuple[int, str]] = {}
            for spec in _specs():
                counter = _DigestCounter(spec.target_columns)
                batch: list[dict[str, Any]] = []
                for transformed in source.rows(spec):
                    counter.add(transformed)
                    batch.append(transformed)
                    if len(batch) >= batch_size:
                        connection.execute(spec.target.insert(), batch)
                        batch.clear()
                if batch:
                    connection.execute(spec.target.insert(), batch)
                expected[spec.target_name] = (counter.rows, counter.hexdigest)
                say(f"Transferred {spec.target_name}: {counter.rows:,} rows")

            table_results = _validate_against_expected(connection, expected)
            say("Exact transformed row counts and digests: OK")

            foreign_key_violations = _foreign_key_violations(connection)
            if foreign_key_violations:
                raise SQLiteTransferError("Foreign-key validation failed: " + "; ".join(foreign_key_violations))
            say("Explicit PostgreSQL foreign-key validation: OK")

            final_source_sha256 = sha256_file(path)
            if final_source_sha256 != source_sha256:
                raise SQLiteTransferError("SQLite source checksum changed during transfer; rolling back target")
            say("SQLite source checksum unchanged")

    return TransferReport(
        source_path=path,
        source_sha256=source_sha256,
        tables=table_results,
        foreign_key_violations=foreign_key_violations,
    )


def validate_sqlite_transfer(source_path: str | Path, engine: Engine) -> TransferReport:
    """Re-run the exact row/digest/FK validation against an already transferred target."""
    path = Path(source_path).expanduser().resolve()
    source_sha256 = sha256_file(path)
    with LegacySQLiteSource(path) as source:
        source.preflight()
        expected = _expected_from_source(source)
        with engine.connect() as connection:
            _ensure_target_schema(connection)
            table_results = _validate_against_expected(connection, expected)
            foreign_key_violations = _foreign_key_violations(connection)
            if foreign_key_violations:
                raise SQLiteTransferError("Foreign-key validation failed: " + "; ".join(foreign_key_violations))
        final_source_sha256 = sha256_file(path)
        if final_source_sha256 != source_sha256:
            raise SQLiteTransferError("SQLite source checksum changed during validation")
    return TransferReport(path, source_sha256, table_results, foreign_key_violations)

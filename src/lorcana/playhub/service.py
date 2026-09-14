"""Application workflows for Play Hub ingestion."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection, Engine

from lorcana.db.tx import transaction
from lorcana.playhub.client import PlayHubClient, PlayHubClientError
from lorcana.playhub.parser import (
    PlayHubParseError,
    extract_event_data,
    latest_generated_standings_round,
    parse_event_bundle,
    parse_match,
    parse_standings,
    select_discovered_events,
    round_should_have_matches,
)
from lorcana.playhub.repository import PlayHubRepository
from lorcana.playhub.types import PlayHubDiscoveryResult, PlayHubImportResult


class PlayHubImportClient(Protocol):
    def fetch_event_html(self, event_id: int) -> str: ...
    def fetch_all_standings(self, round_id: int) -> list[dict[str, Any]]: ...
    def fetch_all_round_matches(self, round_id: int) -> list[dict[str, Any]]: ...


TransactionFactory = Callable[[], AbstractContextManager[Connection]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _error_category(error: Exception) -> str:
    if isinstance(error, PlayHubClientError):
        return "client_error"
    if isinstance(error, PlayHubParseError):
        return "parse_error"
    return "import_error"


class PlayHubImportService:
    def __init__(
        self,
        *,
        client: PlayHubImportClient,
        repository: PlayHubRepository,
        transaction_factory: TransactionFactory,
        clock: Callable[[], datetime] = _utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ):
        self.client = client
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.clock = clock
        self.uuid_factory = uuid_factory

    @classmethod
    def from_engine(
        cls,
        engine: Engine,
        *,
        client: PlayHubImportClient | None = None,
        repository: PlayHubRepository | None = None,
    ) -> "PlayHubImportService":
        return cls(
            client=client or PlayHubClient(),
            repository=repository or PlayHubRepository(),
            transaction_factory=lambda: transaction(engine),
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("PlayHubImportService clock must return timezone-aware datetimes")
        return value.astimezone(timezone.utc)

    def _persist_event_bundle(self, connection: Connection, bundle) -> None:
        if bundle.store is not None:
            self.repository.upsert_store(connection, bundle.store)
        self.repository.upsert_event(connection, bundle.event)
        for phase in bundle.phases:
            self.repository.upsert_phase(connection, phase)
        for round_record in bundle.rounds:
            self.repository.upsert_round(connection, round_record)

    def import_event(self, event_id: int, *, event_data: dict[str, Any] | None = None) -> PlayHubImportResult:
        observed_at = self._now()
        if event_data is None:
            html = self.client.fetch_event_html(event_id)
            event_data = extract_event_data(html, event_id)
        bundle = parse_event_bundle(event_data, event_id, observed_at=observed_at)

        import_attempt_id = self.uuid_factory()
        attempt_started = False
        rounds_expected = 0
        rounds_imported = 0
        registrations_found = 0
        matches_found = 0
        failed_round_ids: list[int] = []

        try:
            match_rounds = tuple(round_record for round_record in bundle.rounds if round_should_have_matches(round_record))
            rounds_expected = len(match_rounds)

            with self.transaction_factory() as connection:
                self._persist_event_bundle(connection, bundle)
                self.repository.start_import_attempt(
                    connection,
                    import_attempt_id=import_attempt_id,
                    event_id=event_id,
                    started_at=observed_at,
                )
                self.repository.set_event_sync_state(
                    connection,
                    event_id=event_id,
                    state="syncing",
                    last_attempt_at=observed_at,
                    last_error_category=None,
                    last_error_summary=None,
                )
            attempt_started = True

            standings_round = latest_generated_standings_round(bundle.rounds)
            if standings_round is not None:
                raw_standings = self.client.fetch_all_standings(standings_round.round_id)
                registrations_found = len(raw_standings)
                standings = parse_standings(event_id, raw_standings, observed_at=self._now())
                with self.transaction_factory() as connection:
                    for player in standings.players:
                        self.repository.upsert_player(connection, player)
                    for registration in standings.registrations:
                        self.repository.upsert_registration(connection, registration)

            for round_record in match_rounds:
                try:
                    raw_matches = self.client.fetch_all_round_matches(round_record.round_id)
                    parsed_matches = tuple(
                        parse_match(event_id, round_record.round_id, raw_match, observed_at=self._now())
                        for raw_match in raw_matches
                    )
                    with self.transaction_factory() as connection:
                        for parsed in parsed_matches:
                            for player in parsed.players:
                                self.repository.upsert_player(connection, player)
                            self.repository.upsert_match(connection, parsed.match)
                    rounds_imported += 1
                    matches_found += len(parsed_matches)
                except Exception:
                    failed_round_ids.append(round_record.round_id)

            if rounds_expected == 0:
                status = "no_results"
                error_category = "no_results"
                error_summary = "No generated PLAY_VS_OPPONENT rounds were found."
            elif rounds_imported == rounds_expected:
                status = "complete"
                error_category = None
                error_summary = None
            else:
                status = "partial"
                error_category = "round_import_partial"
                error_summary = (
                    f"Imported {rounds_imported} of {rounds_expected} expected rounds; "
                    f"failed round IDs: {', '.join(str(value) for value in failed_round_ids)}"
                )

            completed_at = self._now()
            with self.transaction_factory() as connection:
                players_found = self.repository.count_distinct_event_players(connection, event_id)
                self.repository.finish_import_attempt(
                    connection,
                    import_attempt_id=import_attempt_id,
                    completed_at=completed_at,
                    status=status,
                    rounds_expected=rounds_expected,
                    rounds_imported=rounds_imported,
                    registrations_found=registrations_found,
                    matches_found=matches_found,
                    players_found=players_found,
                    error_category=error_category,
                    error_summary=error_summary,
                )
                self.repository.set_event_sync_state(
                    connection,
                    event_id=event_id,
                    state=status,
                    last_attempt_at=observed_at,
                    last_success_at=completed_at if status == "complete" else None,
                    last_error_category=error_category,
                    last_error_summary=error_summary,
                )

            return PlayHubImportResult(
                event_id=event_id,
                status=status,
                rounds_expected=rounds_expected,
                rounds_imported=rounds_imported,
                registrations_found=registrations_found,
                matches_found=matches_found,
                players_found=players_found,
                import_attempt_id=import_attempt_id,
                failed_round_ids=tuple(failed_round_ids),
            )

        except Exception as error:
            if attempt_started:
                failed_at = self._now()
                category = _error_category(error)
                with self.transaction_factory() as connection:
                    players_found = self.repository.count_distinct_event_players(connection, event_id)
                    self.repository.finish_import_attempt(
                        connection,
                        import_attempt_id=import_attempt_id,
                        completed_at=failed_at,
                        status="failed",
                        rounds_expected=rounds_expected,
                        rounds_imported=rounds_imported,
                        registrations_found=registrations_found,
                        matches_found=matches_found,
                        players_found=players_found,
                        error_category=category,
                        error_summary=str(error),
                    )
                    self.repository.set_event_sync_state(
                        connection,
                        event_id=event_id,
                        state="failed",
                        last_attempt_at=observed_at,
                        last_error_category=category,
                        last_error_summary=str(error),
                    )
            raise


class PlayHubDiscoveryClient(Protocol):
    def fetch_all_discovered_events(self, start_date: str, end_date_exclusive: str) -> list[dict[str, Any]]: ...


class PlayHubDiscoveryService:
    """Discover event source facts without importing tournament results."""

    def __init__(
        self,
        *,
        client: PlayHubDiscoveryClient,
        repository: PlayHubRepository,
        transaction_factory: TransactionFactory,
        clock: Callable[[], datetime] = _utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ):
        self.client = client
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.clock = clock
        self.uuid_factory = uuid_factory

    @classmethod
    def from_engine(
        cls,
        engine: Engine,
        *,
        client: PlayHubDiscoveryClient | None = None,
        repository: PlayHubRepository | None = None,
    ) -> "PlayHubDiscoveryService":
        return cls(
            client=client or PlayHubClient(),
            repository=repository or PlayHubRepository(),
            transaction_factory=lambda: transaction(engine),
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("PlayHubDiscoveryService clock must return timezone-aware datetimes")
        return value.astimezone(timezone.utc)

    def sync_range(
        self,
        start_day: date,
        end_day_exclusive: date,
        *,
        force: bool = False,
    ) -> PlayHubDiscoveryResult:
        if end_day_exclusive <= start_day:
            raise ValueError("end_day_exclusive must be after start_day")
        if (end_day_exclusive - start_day).days > 366:
            raise ValueError("discovery windows may not exceed 366 days")

        start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(end_day_exclusive, time.min, tzinfo=timezone.utc)

        if not force:
            with self.transaction_factory() as connection:
                if self.repository.has_completed_discovery_window(
                    connection, start_datetime=start, end_datetime=end
                ):
                    return PlayHubDiscoveryResult(
                        discovery_run_id=None,
                        start_datetime=start,
                        end_datetime=end,
                        events_received=0,
                        unique_events=0,
                        duplicate_rows=0,
                        persisted_events=0,
                        skipped=True,
                    )

        run_id = self.uuid_factory()
        started_at = self._now()
        with self.transaction_factory() as connection:
            self.repository.start_discovery_run(
                connection,
                discovery_run_id=run_id,
                started_at=started_at,
                start_datetime=start,
                end_datetime=end,
            )

        events_received = 0
        unique_events = 0
        duplicate_rows = 0
        try:
            raw_events = self.client.fetch_all_discovered_events(
                start_day.isoformat(),
                end_day_exclusive.isoformat(),
            )
            events_received = len(raw_events)
            selection = select_discovered_events(
                raw_events,
                start_datetime=start,
                end_datetime=end,
            )
            unique_events = len(selection.events)
            duplicate_rows = selection.duplicate_rows
            observed_at = self._now()
            bundles = tuple(
                parse_event_bundle(raw_event, int(raw_event["id"]), observed_at=observed_at)
                for raw_event in selection.events
            )

            completed_at = self._now()
            with self.transaction_factory() as connection:
                for bundle in bundles:
                    if bundle.store is not None:
                        self.repository.upsert_store(connection, bundle.store)
                    self.repository.upsert_event(connection, bundle.event)
                    self.repository.ensure_event_sync_state(
                        connection, event_id=bundle.event.event_id
                    )
                self.repository.finish_discovery_run(
                    connection,
                    discovery_run_id=run_id,
                    completed_at=completed_at,
                    status="complete",
                    events_received=events_received,
                    unique_events=unique_events,
                    duplicate_rows=duplicate_rows,
                )

            return PlayHubDiscoveryResult(
                discovery_run_id=run_id,
                start_datetime=start,
                end_datetime=end,
                events_received=events_received,
                unique_events=unique_events,
                duplicate_rows=duplicate_rows,
                persisted_events=len(bundles),
            )
        except Exception as error:
            failed_at = self._now()
            with self.transaction_factory() as connection:
                self.repository.finish_discovery_run(
                    connection,
                    discovery_run_id=run_id,
                    completed_at=failed_at,
                    status="failed",
                    events_received=events_received,
                    unique_events=unique_events,
                    duplicate_rows=duplicate_rows,
                    error_category=_error_category(error),
                    error_summary=str(error),
                )
            raise

    def sync_day(self, day: date, *, force: bool = False) -> PlayHubDiscoveryResult:
        return self.sync_range(day, day + timedelta(days=1), force=force)

class PlayHubMaintenanceService:
    """Read-only selection of source events that need retryable import work."""

    def __init__(
        self,
        *,
        repository: PlayHubRepository,
        read_connection_factory: Callable[[], AbstractContextManager[Connection]],
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository = repository
        self.read_connection_factory = read_connection_factory
        self.clock = clock

    @classmethod
    def from_engine(
        cls,
        engine: Engine,
        *,
        repository: PlayHubRepository | None = None,
        **kwargs,
    ) -> "PlayHubMaintenanceService":
        from contextlib import contextmanager

        @contextmanager
        def reader():
            with engine.connect() as connection:
                yield connection

        return cls(
            repository=repository or PlayHubRepository(),
            read_connection_factory=reader,
            **kwargs,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("PlayHubMaintenanceService clock must return timezone-aware datetimes")
        return value.astimezone(timezone.utc)

    def due_event_import_ids(
        self,
        *,
        lookback_days: int = 14,
        retry_minutes: int = 60,
        limit: int = 500,
    ) -> tuple[int, ...]:
        if not 1 <= lookback_days <= 3650:
            raise ValueError("lookback_days must be between 1 and 3650")
        if retry_minutes < 1:
            raise ValueError("retry_minutes must be positive")
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")
        now = self._now()
        with self.read_connection_factory() as connection:
            return self.repository.due_event_import_ids(
                connection,
                now=now,
                lookback_start=now - timedelta(days=lookback_days),
                retry_before=now - timedelta(minutes=retry_minutes),
                limit=limit,
            )


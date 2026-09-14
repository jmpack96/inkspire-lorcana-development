from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from lorcana.playhub.parser import PlayHubParseError, select_discovered_events
from lorcana.playhub.service import PlayHubDiscoveryService

NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)


def event(event_id, start="2026-09-13T12:00:00Z"):
    return {
        "id": event_id,
        "name": f"Event {event_id}",
        "start_datetime": start,
        "gameplay_format": {"id": "core", "name": "Core"},
        "store": {"id": f"store-{event_id}", "name": "Store"},
    }


def test_discovery_window_dedupes_and_excludes_inclusive_end_boundary():
    selection = select_discovered_events(
        [
            event(1),
            event(1),
            event(2, "2026-09-14T00:00:00Z"),
            {"id": 3, "name": "No date"},
            {"name": "No id", "start_datetime": "2026-09-13T12:00:00Z"},
        ],
        start_datetime=datetime(2026, 9, 13, tzinfo=timezone.utc),
        end_datetime=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    assert [row["id"] for row in selection.events] == [1]
    assert selection.events_received == 5
    assert selection.duplicate_rows == 1
    assert selection.boundary_excluded == 1
    assert selection.missing_datetime == 1
    assert selection.missing_id == 1


def test_discovery_window_rejects_truly_out_of_range_event():
    with pytest.raises(PlayHubParseError, match="outside requested window"):
        select_discovered_events(
            [event(1, "2026-09-15T00:00:00Z")],
            start_datetime=datetime(2026, 9, 13, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def fetch_all_discovered_events(self, start_date, end_date_exclusive):
        self.calls.append((start_date, end_date_exclusive))
        if isinstance(self.rows, Exception):
            raise self.rows
        return list(self.rows)


class FakeRepository:
    def __init__(self):
        self.completed = False
        self.runs = {}
        self.events = {}
        self.stores = {}
        self.sync = {}

    def has_completed_discovery_window(self, _c, **_values): return self.completed
    def start_discovery_run(self, _c, **values): self.runs[values["discovery_run_id"]] = {**values, "status": "running"}
    def finish_discovery_run(self, _c, **values): self.runs[values["discovery_run_id"]].update(values)
    def upsert_store(self, _c, row): self.stores[row.store_id] = row
    def upsert_event(self, _c, row): self.events[row.event_id] = row
    def ensure_event_sync_state(self, _c, *, event_id, state="discovered"): self.sync.setdefault(event_id, state)


@contextmanager
def tx():
    yield object()


def make_service(client, repository, run_id):
    return PlayHubDiscoveryService(
        client=client,
        repository=repository,
        transaction_factory=lambda: tx(),
        clock=lambda: NOW,
        uuid_factory=lambda: run_id,
    )


def test_discovery_service_persists_events_and_run_history():
    run_id = UUID("00000000-0000-0000-0000-000000000101")
    rows = [event(1), event(1), event(2, "2026-09-14T00:00:00Z")]
    client = FakeClient(rows)
    repository = FakeRepository()

    result = make_service(client, repository, run_id).sync_day(date(2026, 9, 13))

    assert result.discovery_run_id == run_id
    assert result.events_received == 3
    assert result.unique_events == 1
    assert result.duplicate_rows == 1
    assert result.persisted_events == 1
    assert set(repository.events) == {1}
    assert repository.sync == {1: "discovered"}
    assert repository.runs[run_id]["status"] == "complete"
    assert client.calls == [("2026-09-13", "2026-09-14")]


def test_discovery_service_skips_completed_window_unless_forced():
    repository = FakeRepository()
    repository.completed = True
    client = FakeClient([event(1)])
    result = make_service(
        client, repository, UUID("00000000-0000-0000-0000-000000000102")
    ).sync_day(date(2026, 9, 13))
    assert result.skipped
    assert client.calls == []
    assert repository.runs == {}


def test_discovery_service_sync_range_uses_exact_half_open_utc_window():
    run_id = UUID("00000000-0000-0000-0000-000000000103")
    repository = FakeRepository()
    client = FakeClient([event(1), event(2, "2026-09-15T23:59:59Z")])

    result = make_service(client, repository, run_id).sync_range(
        date(2026, 9, 13), date(2026, 9, 16)
    )

    assert result.start_datetime == datetime(2026, 9, 13, tzinfo=timezone.utc)
    assert result.end_datetime == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert result.persisted_events == 2
    assert client.calls == [("2026-09-13", "2026-09-16")]


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2026, 9, 13), date(2026, 9, 13)),
        (date(2026, 9, 14), date(2026, 9, 13)),
        (date(2026, 1, 1), date(2027, 1, 3)),
    ],
)
def test_discovery_service_sync_range_validates_window(start, end):
    with pytest.raises(ValueError):
        make_service(
            FakeClient([]),
            FakeRepository(),
            UUID("00000000-0000-0000-0000-000000000104"),
        ).sync_range(start, end)

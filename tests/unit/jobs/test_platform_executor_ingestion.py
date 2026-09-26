from __future__ import annotations

from datetime import date

import pytest

import lorcana.jobs.executor as executor_module
from lorcana.jobs.executor import PermanentJobError, PlatformJobExecutor


class FakeQueue:
    pass


def bare_executor():
    executor = PlatformJobExecutor.__new__(PlatformJobExecutor)
    executor.engine = object()
    executor.queue = FakeQueue()
    executor.analyzer_registry = None
    return executor

def test_discover_window_supports_past_and_future_overlap(monkeypatch):
    calls = []

    class Client:
        def close(self):
            calls.append(("closed",))

    class Service:
        def sync_range(self, start, end, *, force):
            calls.append((start, end, force))
            return type(
                "Result",
                (),
                {
                    "events_received": 0,
                    "unique_events": 0,
                    "persisted_events": 0,
                    "skipped": False,
                },
            )()

    monkeypatch.setattr(executor_module, "PlayHubClient", Client)

    monkeypatch.setattr(
        executor_module.PlayHubDiscoveryService,
        "from_engine",
        classmethod(lambda cls, engine, *, client=None: Service()),
    )

    result = bare_executor()._discover_window(
        {
            "anchor_date": "2026-09-14",
            "lookback_days": 30,
            "lookahead_days": 30,
            "chunk_days": 7,
            "force": False,
        }
    )

    assert result["start_date"] == "2026-08-15"
    assert result["end_date_exclusive"] == "2026-10-15"

    assert calls[-1] == ("closed",)

def test_discover_window_chunks_range_and_aggregates(monkeypatch):
    calls = []

    class Client:
        def close(self):
            calls.append(("closed",))

    class Service:
        def sync_range(self, start, end, *, force):
            calls.append((start, end, force))
            return type(
                "Result",
                (),
                {
                    "events_received": 10,
                    "unique_events": 8,
                    "persisted_events": 8,
                    "skipped": False,
                },
            )()

    monkeypatch.setattr(executor_module, "PlayHubClient", Client)
    monkeypatch.setattr(
        executor_module.PlayHubDiscoveryService,
        "from_engine",
        classmethod(lambda cls, engine, *, client=None: Service()),
    )

    result = bare_executor()._discover_window(
        {
            "start_date": "2026-09-13",
            "lookahead_days": 9,
            "chunk_days": 4,
            "force": False,
        }
    )

    assert calls[:-1] == [
        (date(2026, 9, 13), date(2026, 9, 17), False),
        (date(2026, 9, 17), date(2026, 9, 21), False),
        (date(2026, 9, 21), date(2026, 9, 23), False),
    ]
    assert calls[-1] == ("closed",)
    assert result == {
        "start_date": "2026-09-13",
        "end_date_exclusive": "2026-09-23",
        "windows": 3,
        "events_received": 30,
        "unique_events": 24,
        "persisted_events": 24,
        "skipped_windows": 0,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"start_date": "bad"},
        {"start_date": "2026-09-13", "lookahead_days": -1},
        {"start_date": "2026-09-13", "lookahead_days": 367},
        {"start_date": "2026-09-13", "chunk_days": 0},
        {"start_date": "2026-09-13", "chunk_days": 32},
    ],
)
def test_discover_window_rejects_bad_payload(payload):
    with pytest.raises(PermanentJobError):
        bare_executor()._discover_window(payload)


def test_import_sweep_enqueues_each_due_event_with_occurrence_generation(monkeypatch):
    class Maintenance:
        def due_event_import_ids(self, **kwargs):
            assert kwargs == {
                "lookback_days": 21,
                "retry_minutes": 90,
                "recent_complete_days": 7,
                "limit": 12,
            }
            return (101, 102, 103)

    monkeypatch.setattr(
        executor_module.PlayHubMaintenanceService,
        "from_engine",
        classmethod(lambda cls, engine: Maintenance()),
    )

    enqueued = []

    def fake_enqueue(queue, event_id, *, generation):
        enqueued.append((queue, event_id, generation))
        return type("Queued", (), {"created": event_id != 102})()

    monkeypatch.setattr(executor_module, "enqueue_event_import", fake_enqueue)
    executor = bare_executor()
    result = executor._enqueue_due_imports(
        {
            "lookback_days": 21,
            "retry_minutes": 90,
            "limit": 12,
            "generation": "2026-09-13T20:00Z",
        }
    )

    assert [(event_id, generation) for _, event_id, generation in enqueued] == [
        (101, "sweep:2026-09-13T20:00Z"),
        (102, "sweep:2026-09-13T20:00Z"),
        (103, "sweep:2026-09-13T20:00Z"),
    ]
    assert result == {
        "candidate_events": 3,
        "import_jobs_created": 2,
        "generation": "2026-09-13T20:00Z",
    }


def test_job_pruning_is_bounded_and_keeps_recent_operational_history():
    captured = {}

    class Repository:
        def prune_completed_before(self, _connection, **values):
            captured.update(values)
            return 37

    class QueueWithTx:
        repository = Repository()

        @staticmethod
        def transaction_factory():
            from contextlib import nullcontext
            return nullcontext(object())

    executor = bare_executor()
    executor.queue = QueueWithTx()
    result = executor._prune_jobs({"retention_days": 45, "limit": 1234})
    assert result == {"deleted_jobs": 37, "retention_days": 45}
    assert captured["limit"] == 1234
    assert captured["completed_before"].tzinfo is not None


@pytest.mark.parametrize(
    "payload",
    [
        {"retention_days": 6},
        {"retention_days": 3651},
        {"limit": 0},
        {"limit": 50001},
    ],
)
def test_job_pruning_rejects_unsafe_bounds(payload):
    with pytest.raises(PermanentJobError):
        bare_executor()._prune_jobs(payload)


def test_live_scan_records_attempts_and_reserves_immediately_after_each_refresh(monkeypatch):
    from types import SimpleNamespace
    from lorcana.config import Settings
    calls = []
    class Alerts:
        def potential_event_ids(self, team):
            return (1, 2, 3)
        def record_refresh_attempt(self, event_id):
            calls.append(("attempt", event_id))
        def reserve_eligible(self, team, channel):
            calls.append(("reserve",))
            return 1
    class Importer:
        def import_event(self, event_id):
            calls.append(("import", event_id))
            if event_id == 2:
                raise RuntimeError("network failure")
    class Client:
        def close(self):
            calls.append(("close",))
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: SimpleNamespace(
        live_event_channel_id=123, discord_team_slug="inkspire")))
    monkeypatch.setattr(executor_module.LiveEventAlertService, "from_engine", classmethod(lambda cls, engine: Alerts()))
    monkeypatch.setattr(executor_module.PlayHubImportService, "from_engine", classmethod(lambda cls, engine, client: Importer()))
    monkeypatch.setattr(executor_module, "PlayHubClient", Client)
    result = bare_executor()._scan_live_events()
    assert result == dict(enabled=True, candidates=3, refreshed=2, refresh_failures=1, queued=3)
    assert calls == [("reserve",), ("attempt", 1), ("import", 1), ("reserve",),
                     ("attempt", 2), ("import", 2), ("attempt", 3), ("import", 3),
                     ("reserve",), ("close",)]

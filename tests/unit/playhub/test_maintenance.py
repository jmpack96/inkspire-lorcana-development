from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from lorcana.playhub.service import PlayHubMaintenanceService

NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)


class Repository:
    def __init__(self):
        self.values = None

    def due_event_import_ids(self, _connection, **values):
        self.values = values
        return (11, 22)


@contextmanager
def reader():
    yield object()

def test_maintenance_service_supports_long_recovery_window():
    repository = Repository()
    service = PlayHubMaintenanceService(
        repository=repository,
        read_connection_factory=reader,
        clock=lambda: NOW,
    )

    service.due_event_import_ids(
        lookback_days=90,
        retry_minutes=180,
        recent_complete_days=7,
        limit=500,
    )

    assert repository.values["lookback_start"] == NOW - timedelta(days=90)
    assert repository.values["retry_before"] == NOW - timedelta(minutes=180)

def test_maintenance_service_derives_retry_cutoffs_from_one_clock_value():
    repository = Repository()
    service = PlayHubMaintenanceService(
        repository=repository,
        read_connection_factory=reader,
        clock=lambda: NOW,
    )

    assert service.due_event_import_ids(
        lookback_days=14,
        retry_minutes=75,
        recent_complete_days=7,
        limit=123,
    ) == (11, 22)
    assert repository.values == {
        "now": NOW,
        "lookback_start": NOW - timedelta(days=14),
        "retry_before": NOW - timedelta(minutes=75),
        "recent_complete_after": NOW - timedelta(days=7),
        "limit": 123,
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lookback_days": 0},
        {"lookback_days": 3651},
        {"retry_minutes": 0},
        {"recent_complete_days": 0},
        {"recent_complete_days": 31},
        {"limit": 0},
        {"limit": 5001},
    ],
)
def test_maintenance_service_validates_bounds(kwargs):
    service = PlayHubMaintenanceService(
        repository=Repository(),
        read_connection_factory=reader,
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError):
        service.due_event_import_ids(**kwargs)

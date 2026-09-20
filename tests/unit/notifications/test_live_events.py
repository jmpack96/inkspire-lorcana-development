from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from lorcana.notifications.live_events import (
    LiveEventAlertService,
    PendingAnnouncement,
    event_date_is_current,
)


NOW = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)


@contextmanager
def connection():
    yield "connection"


class Repository:
    def potential_event_ids(self, connection, **values):
        self.potential_values = values
        return (101,)

    def eligible_events(self, connection, **values):
        self.eligible_values = values
        return ({
            "event_id": 101,
            "source_url": "https://tcg.ravensburgerplay.com/events/101",
            "end_datetime": NOW + timedelta(hours=1),
            "start_datetime": NOW - timedelta(hours=1),
            "timezone": "America/New_York",
        },)

    def reserve(self, connection, **values):
        self.reserved = values
        return True

    def next_pending(self, connection, **values):
        return {
            "announcement_id": 1,
            "event_id": 101,
            "channel_id": 999,
            "event_url": "https://tcg.ravensburgerplay.com/events/101",
            "expires_at": NOW + timedelta(hours=1),
            "attempt_count": 0,
        }


def service(repository):
    return LiveEventAlertService(
        repository=repository,
        connection_factory=connection,
        transaction_factory=connection,
        clock=lambda: NOW,
    )


def test_reservation_uses_fresh_active_event_and_is_idempotent_at_repository():
    repository = Repository()
    alerts = service(repository)

    assert alerts.potential_event_ids("inkspire") == (101,)
    assert alerts.reserve_eligible("inkspire", 999) == 1

    assert repository.eligible_values["now"] == NOW
    assert repository.eligible_values["fresh_after"] == NOW - timedelta(minutes=10)
    assert repository.reserved["event_id"] == 101
    assert repository.reserved["channel_id"] == 999
    assert repository.reserved["expires_at"] == NOW + timedelta(hours=1)


def test_pending_announcement_preserves_expiry_for_delivery_guard():
    pending = service(Repository()).next_pending()

    assert isinstance(pending, PendingAnnouncement)
    assert pending.expires_at > NOW


def test_event_date_must_be_today_in_event_timezone_even_when_marked_live():
    now = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)

    assert event_date_is_current(
        datetime(2026, 9, 19, 22, 0, tzinfo=timezone.utc),
        "America/New_York",
        now,
    )
    assert not event_date_is_current(
        datetime(2026, 9, 18, 22, 0, tzinfo=timezone.utc),
        "America/New_York",
        now,
    )
    assert not event_date_is_current(now, None, now)

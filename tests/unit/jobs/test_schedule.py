from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lorcana.jobs.schedule import materialize_scheduled_payload, next_occurrence


def test_interval_schedule_is_strictly_after_base():
    base = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)
    assert next_occurrence({"type": "interval", "seconds": 3600}, base) == datetime(
        2026, 9, 13, 21, 0, tzinfo=timezone.utc
    )


def test_daily_schedule_respects_named_timezone_and_dst():
    # 06:00 America/New_York is 10:00 UTC during daylight time.
    base = datetime(2026, 9, 13, 9, 0, tzinfo=timezone.utc)
    assert next_occurrence(
        {"type": "daily", "hour": 6, "minute": 0, "timezone": "America/New_York"},
        base,
    ) == datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc)

    # After the November DST transition, 06:00 local is 11:00 UTC.
    winter = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    assert next_occurrence(
        {"type": "daily", "hour": 6, "minute": 0, "timezone": "America/New_York"},
        winter,
    ) == datetime(2026, 11, 9, 11, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "interval", "seconds": 30},
        {"type": "daily", "hour": 24, "minute": 0, "timezone": "UTC"},
        {"type": "daily", "hour": 6, "minute": 0, "timezone": "Not/AZone"},
        {"type": "unknown"},
    ],
)
def test_invalid_schedule_specs_are_rejected(spec):
    with pytest.raises(ValueError):
        next_occurrence(spec, datetime(2026, 9, 13, tzinfo=timezone.utc))


def test_materialize_scheduled_payload_replaces_reserved_occurrence_tokens_recursively():
    scheduled = datetime(2026, 9, 14, 3, 30, tzinfo=timezone.utc)
    payload = {
        "day": "$scheduled_date",
        "scheduled": "$scheduled_at",
        "nested": ["keep", {"again": "$scheduled_date"}],
    }
    assert materialize_scheduled_payload(payload, scheduled) == {
        "day": "2026-09-14",
        "scheduled": "2026-09-14T03:30:00+00:00",
        "nested": ["keep", {"again": "2026-09-14"}],
    }


def test_materialize_scheduled_payload_requires_aware_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        materialize_scheduled_payload({"day": "$scheduled_date"}, datetime(2026, 9, 14))

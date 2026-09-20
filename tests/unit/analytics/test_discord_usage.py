from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from lorcana.analytics.service import DiscordUsageService


NOW = datetime(2026, 9, 20, 14, 0, tzinfo=timezone.utc)


class Repository:
    def __init__(self):
        self.recorded = None

    def record(self, connection, **values):
        self.recorded = (connection, values)

    def overall(self, connection, *, start_at):
        self.start_at = start_at
        return {"invocations": 4, "unique_users": 3, "failures": 1}

    def summary_rows(self, connection, *, start_at):
        assert start_at == self.start_at
        return ({
            "command_name": "player",
            "invocations": 4,
            "unique_users": 3,
            "failures": 1,
            "average_duration_ms": 12.6,
            "team_selector_invocations": 3,
        },)


@contextmanager
def connection():
    yield "connection"


def service(repository=None):
    return DiscordUsageService(
        repository=repository or Repository(),
        transaction_factory=connection,
        connection_factory=connection,
        clock=lambda: NOW,
    )


def test_record_passes_privacy_safe_usage_fields_to_repository():
    repository = Repository()
    usage = service(repository)

    usage.record(
        command_name=" player ",
        invocation_mode=" direct_query ",
        discord_user_id=123,
        guild_id=456,
        succeeded=True,
        duration_ms=17,
    )

    connection_value, values = repository.recorded
    assert connection_value == "connection"
    assert values == {
        "occurred_at": NOW,
        "command_name": "player",
        "invocation_mode": "direct_query",
        "discord_user_id": 123,
        "guild_id": 456,
        "succeeded": True,
        "duration_ms": 17,
    }


def test_summary_builds_typed_usage_report():
    usage = service()

    summary = usage.summary(days=30)

    assert summary.invocations == 4
    assert summary.unique_users == 3
    assert summary.failures == 1
    assert summary.entries[0].command_name == "player"
    assert summary.entries[0].average_duration_ms == 13
    assert summary.entries[0].team_selector_invocations == 3


@pytest.mark.parametrize("days", [0, 366])
def test_summary_rejects_days_outside_supported_range(days):
    with pytest.raises(ValueError):
        service().summary(days=days)

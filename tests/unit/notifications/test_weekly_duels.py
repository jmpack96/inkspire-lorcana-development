from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from lorcana.db.schema.notifications import discord_weekly_duels_posts
from lorcana.notifications.weekly_duels import WeeklyDuelsDelivery


@compiles(JSONB, "sqlite")
def sqlite_jsonb(element, compiler, **kwargs):
    return "JSON"


class Service:
    team_slug = "inkspire"
    calls = 0
    def report(self, **kwargs):
        self.calls += 1
        return dict(start=kwargs["since"], end=kwargs["until"], missing=[], rows=[dict(player="Jacob", games=0, decks=[], most_losses=[], loss_count=0, unknown_losses=0)] * 100)


def test_delivery_snapshot_lease_restart_progress_and_completion():
    engine = create_engine("sqlite://")
    discord_weekly_duels_posts.create(engine)
    now = [datetime(2026, 10, 4, 13, tzinfo=timezone.utc)]
    service = Service()
    delivery = WeeklyDuelsDelivery(engine, service, channel_id=987654321, clock=lambda: now[0])
    first = delivery.claim()
    assert first["next_page"] == 0
    assert first["channel_id"] == 987654321
    assert delivery.claim() is None  # concurrent instance cannot send
    now[0] += timedelta(minutes=11)  # recover a crashed sender
    second = delivery.claim()
    assert second is not None and service.calls == 1
    import pytest
    with pytest.raises(RuntimeError, match="lease was lost"):
        delivery.advance(first, 1)
    delivery.advance(second, 1)
    delivery.release(second)
    resumed = delivery.claim()
    assert resumed["next_page"] == 1 and resumed["pages"] == second["pages"]
    delivery.advance(resumed, len(resumed["pages"]))
    delivery.release(resumed)
    assert delivery.claim() is None  # no duplicate after restart
    now[0] += timedelta(days=7)
    assert delivery.claim() is not None
    assert service.calls == 2

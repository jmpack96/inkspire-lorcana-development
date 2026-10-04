"""Sunday scheduling and leased, restart-safe report delivery."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, or_
from sqlalchemy.dialects.postgresql import insert

from lorcana.db.schema.notifications import discord_weekly_duels_posts as posts
from lorcana.duels.weekly import latest_weekly_boundary, previous_weekly_boundary
from lorcana.interfaces.discord.weekly_duels_views import weekly_views


class WeeklyDuelsDelivery:
    def __init__(self, engine, service, *, channel_id, clock=lambda: datetime.now(timezone.utc)):
        self.engine, self.service, self.clock = engine, service, clock
        self.channel_id = channel_id

    def _key(self, end):
        return (posts.c.team_slug == self.service.team_slug) & (posts.c.channel_id == self.channel_id) & (posts.c.period_end == end)

    def claim(self):
        now = self.clock()
        end = latest_weekly_boundary(now)
        key = self._key(end)
        with self.engine.connect() as connection:
            exists = connection.execute(select(posts.c.period_end).where(key)).first()
        if exists is None:
            report = self.service.report(until=end, since=previous_weekly_boundary(end))
            pages = [asdict(page) for page in weekly_views(report)]
            with self.engine.begin() as connection:
                connection.execute(insert(posts).values(team_slug=self.service.team_slug,
                    channel_id=self.channel_id, period_end=end, pages=pages).on_conflict_do_nothing())
        # A persisted lease prevents concurrent bot instances from delivering the same page.
        lease = now + timedelta(minutes=10)
        with self.engine.begin() as connection:
            row = connection.execute(update(posts).where(key, posts.c.sent_at.is_(None),
                or_(posts.c.lease_until.is_(None), posts.c.lease_until <= now))
                .values(lease_until=lease).returning(posts)).mappings().one_or_none()
        return None if row is None else dict(row)

    def advance(self, claim, next_page):
        now = self.clock()
        renewed = now + timedelta(minutes=10)
        with self.engine.begin() as connection:
            result = connection.execute(update(posts).where(self._key(claim["period_end"]),
                posts.c.lease_until == claim["lease_until"]).values(
                next_page=next_page, lease_until=renewed,
                sent_at=now if next_page == len(claim["pages"]) else None))
            if result.rowcount != 1:
                raise RuntimeError("Weekly Duels delivery lease was lost")
        claim["lease_until"] = renewed

    def release(self, claim):
        with self.engine.begin() as connection:
            connection.execute(update(posts).where(self._key(claim["period_end"]),
                posts.c.lease_until == claim["lease_until"]).values(lease_until=None))

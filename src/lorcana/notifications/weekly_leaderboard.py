"""Claim and record Monday evening leaderboard deliveries."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, update
from sqlalchemy.dialects.postgresql import insert

from lorcana.db.schema.notifications import discord_weekly_leaderboard_posts as posts

EASTERN = ZoneInfo("America/New_York")


class WeeklyLeaderboardDelivery:
    def __init__(self, engine, *, team_slug, channel_id):
        self.engine = engine
        self.team_slug = team_slug
        self.channel_id = channel_id

    def _key(self, scheduled_at):
        return (
            posts.c.team_slug == self.team_slug,
            posts.c.channel_id == self.channel_id,
            posts.c.scheduled_at == scheduled_at,
        )

    def claim(self):
        now = datetime.now(timezone.utc)
        local = now.astimezone(EASTERN)
        if local.weekday() != 0 or local.hour < 18:
            return None
        scheduled_at = local.replace(hour=18, minute=0, second=0, microsecond=0)
        lease = now + timedelta(minutes=10)
        with self.engine.begin() as connection:
            connection.execute(
                insert(posts).values(
                    team_slug=self.team_slug,
                    channel_id=self.channel_id,
                    scheduled_at=scheduled_at,
                ).on_conflict_do_nothing()
            )
            return connection.execute(
                update(posts).where(
                    *self._key(scheduled_at),
                    posts.c.sent_at.is_(None),
                    or_(posts.c.lease_until.is_(None), posts.c.lease_until <= now),
                ).values(lease_until=lease).returning(posts.c.scheduled_at, posts.c.lease_until)
            ).one_or_none()

    def finish(self, claim, *, sent):
        with self.engine.begin() as connection:
            connection.execute(
                update(posts).where(
                    *self._key(claim.scheduled_at),
                    posts.c.lease_until == claim.lease_until,
                ).values(
                    lease_until=None,
                    sent_at=datetime.now(timezone.utc) if sent else None,
                )
            )

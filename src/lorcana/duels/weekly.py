"""Seven-day team activity, using history only and one observation per member/game."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from lorcana.duels.matchups import MatchupRepository, color_pair

WEEKLY_TIMEZONE = ZoneInfo("America/New_York")


def latest_weekly_boundary(now):
    local = now.astimezone(WEEKLY_TIMEZONE)
    boundary = local.replace(hour=9, minute=0, second=0, microsecond=0)
    boundary -= timedelta(days=(local.weekday() - 6) % 7)
    if boundary > local:
        boundary -= timedelta(days=7)
    return boundary.astimezone(timezone.utc)


def previous_weekly_boundary(end):
    return (end.astimezone(WEEKLY_TIMEZONE) - timedelta(days=7)).astimezone(timezone.utc)


def aggregate_weekly(names, results):
    stats = {member: {"games": 0, "decks": defaultdict(Counter)}
             for member in names}
    for row in results:
        if row["member_id"] not in stats:
            continue
        stat = stats[row["member_id"]]
        count = row["games"]
        outcome = str(row["result"] or "").strip().lower()
        outcome = {"won": "win", "lost": "loss", "tie": "draw"}.get(outcome, outcome)
        if outcome not in {"win", "loss", "draw"}:
            outcome = "unknown"
        stat["games"] += count
        stat["decks"][color_pair(row["your_deck_colors"])][outcome] += count
    rows = []
    for member, name in sorted(names.items(), key=lambda item: (item[1].casefold(), str(item[0]))):
        stat = stats[member]
        rows.append({"player": name, "games": stat["games"],
                     "decks": [{"colors": colors, **{k: counts[k] for k in ("win", "loss", "draw", "unknown")}}
                               for colors, counts in sorted(stat["decks"].items())]})
    return rows


def team_opponent_losses(names, results):
    """Pool losses against opponents across all members and all of their decks."""
    losses = Counter()
    for row in results:
        if row["member_id"] in names and str(row["result"] or "").strip().lower() in {"loss", "lost"}:
            losses[color_pair(row["opponent_deck_colors"])] += row["games"]
    known = {colors: count for colors, count in losses.items() if colors != "Unknown"}
    most = max(known.values(), default=0)
    return {"colors": sorted(colors for colors, count in known.items() if count == most),
            "count": most, "unknown": losses["Unknown"]}


class WeeklyDuelsService:
    def __init__(self, *, repository, connection_factory, team_slug,
                 clock=lambda: datetime.now(timezone.utc)):
        self.repository, self.connection_factory = repository, connection_factory
        self.team_slug, self.clock = team_slug, clock

    @classmethod
    def from_engine(cls, engine, *, team_slug):
        return cls(repository=MatchupRepository(), connection_factory=engine.connect, team_slug=team_slug)

    def report(self, viewer_id=None, *, until=None, since=None):
        end = until or self.clock()
        start = since or end - timedelta(days=7)
        with self.connection_factory() as connection:
            roster = self.repository.roster(connection, self.team_slug)
            if viewer_id is not None and self.repository.viewer(connection, viewer_id) not in {r["member_id"] for r in roster}:
                raise ValueError("Link your Discord account to an active member of this team to view Duels summaries.")
            names = {r["member_id"]: r["preferred_display_name"] for r in
                     self.repository.roster(connection, self.team_slug, duels_only=True)}
            # results uses an inclusive end; use the immediately preceding microsecond
            # to make adjacent scheduled weeks disjoint [start, end).
            results = self.repository.results(connection, member_ids=list(names), since=start,
                                              until=end - timedelta(microseconds=1))
            coverage = self.repository.coverage(connection, list(names))
        return {"start": start, "end": end, "rows": aggregate_weekly(names, results),
                "opponent_losses": team_opponent_losses(names, results),
                "coverage": {r["member_id"]: r["last_sync"] for r in coverage},
                "missing": [names[m] for m in names if not any(r["member_id"] == m and r["last_sync"] for r in coverage)]}

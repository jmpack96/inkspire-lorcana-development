"""Team Duels summary from history and compact, member-owned opening evidence."""
from collections import Counter, defaultdict
from lorcana.duels.opening_projection import validated_mulligan, PROJECTION_VERSION
from datetime import datetime, timezone

from sqlalchemy import select

from lorcana.cache import ReadCache
from lorcana.db.schema.duels import (
    duels_connections as accounts, duels_games as games,
    duels_game_observations as observations, duels_normalizations as normalizations,
    duels_replays as replays, duels_read_models as read_models,
)
from lorcana.duels.matchups import MatchupRepository, color_pair, current_set
from lorcana.duels.replay_parser import PARSER_VERSION




class DuelsSummaryRepository(MatchupRepository):
    def history(self, connection, *, member_ids, since, until):
        # One observation per member/game, even when they have multiple accounts.
        latest = select(
            accounts.c.member_id, observations.c.connection_id, observations.c.game_id,
            observations.c.your_deck_colors,
        ).select_from(observations.join(accounts).join(games)).where(
            accounts.c.member_id.in_(member_ids), games.c.started_at >= since,
            games.c.started_at <= until,
        ).distinct(accounts.c.member_id, observations.c.game_id).order_by(
            accounts.c.member_id, observations.c.game_id,
            observations.c.last_seen_at.desc(), observations.c.connection_id,
        ).cte("latest_observations")
        # Pick the latest valid source first. A missing projection stays unknown;
        # never substitute an older replay or fetch the giant JSON as a fallback.
        source = select(
            latest.c.member_id, latest.c.game_id, normalizations.c.normalization_id,
        ).select_from(latest.join(replays,
            (replays.c.game_id == latest.c.game_id) &
            (replays.c.connection_id == latest.c.connection_id)).join(normalizations)).where(
            replays.c.status == "valid", normalizations.c.status == "valid",
            normalizations.c.parser_version == PARSER_VERSION,
        ).distinct(latest.c.member_id, latest.c.game_id).order_by(
            latest.c.member_id, latest.c.game_id, replays.c.fetched_at.desc(),
            normalizations.c.created_at.desc(), normalizations.c.normalization_id,
        ).subquery()
        compact = source.outerjoin(read_models,
            (read_models.c.normalization_id == source.c.normalization_id) &
            (read_models.c.version == PROJECTION_VERSION))
        counts = select(source.c.member_id, source.c.game_id,
                        read_models.c.mulligan_count,
                        read_models.c.normalization_id.is_(None).label("projection_pending")
                        ).select_from(compact).subquery()
        query = select(latest, counts.c.mulligan_count, counts.c.projection_pending).select_from(latest.outerjoin(counts,
            (counts.c.member_id == latest.c.member_id) & (counts.c.game_id == latest.c.game_id)))
        # Stream the complete period in batches; no arbitrary history/replay cap.
        return connection.execution_options(yield_per=500).execute(query).mappings()


class DuelsSummaryService:
    def __init__(self, *, repository, connection_factory, team_slug,
                 clock=lambda: datetime.now(timezone.utc)):
        self._cache = ReadCache()
        self.repository, self.connection_factory = repository, connection_factory
        self.team_slug, self.clock = team_slug, clock

    @classmethod
    def from_engine(cls, engine, *, team_slug):
        return cls(repository=DuelsSummaryRepository(), connection_factory=engine.connect,
                   team_slug=team_slug)

    def report(self, viewer_id):
        # Authorization stays live even when another member populated the cache.
        with self.connection_factory() as connection:
            roster = self.repository.roster(connection, self.team_slug)
            if self.repository.viewer(connection, viewer_id) not in {r["member_id"] for r in roster}:
                raise ValueError("Link your Discord account to an active member of this team to view Duels summaries.")
            configured = self.repository.roster(connection, self.team_slug, duels_only=True)
        key = tuple(sorted((str(r["member_id"]), r["preferred_display_name"]) for r in configured))
        return self._cache.get((self.clock().date(), key), lambda: self._report(viewer_id))

    def _report(self, viewer_id):
        now = self.clock()
        with self.connection_factory() as connection:
            roster = self.repository.roster(connection, self.team_slug)
            names = {r["member_id"]: r["preferred_display_name"] for r in roster}
            if self.repository.viewer(connection, viewer_id) not in names:
                raise ValueError("Link your Discord account to an active member of this team to view Duels summaries.")
            roster = self.repository.roster(connection, self.team_slug, duels_only=True)
            names = {r["member_id"]: r["preferred_display_name"] for r in roster}
            catalog = self.repository.catalog(connection)
            period = current_set(catalog["metadata_json"] if catalog else {}, now)
            coverage = self.repository.coverage(connection, list(names))
            pending = 0
            stats = defaultdict(lambda: {"games": 0, "colors": Counter(), "mulligan_sum": 0, "sample": 0})
            for row in self.repository.history(connection, member_ids=list(names),
                                               since=period["start"], until=now):
                member = row["member_id"]
                if member not in names:
                    continue
                stat = stats[member]
                stat["games"] += 1
                pending += bool(row.get("projection_pending"))
                colors = color_pair(row["your_deck_colors"])
                if colors != "Unknown":
                    stat["colors"][colors] += 1
                mulligan = row["mulligan_count"]
                if mulligan is not None:
                    stat["mulligan_sum"] += mulligan
                    stat["sample"] += 1
        rows = []
        for member, name in sorted(names.items(), key=lambda item: (item[1].casefold(), str(item[0]))):
            stat = stats[member]
            top = max(stat["colors"].values(), default=0)
            rows.append({"player": name, "games": stat["games"],
                         "known_colors": sum(stat["colors"].values()), "top_count": top,
                         "top_colors": sorted(k for k, n in stat["colors"].items() if n == top),
                         "mulligan_average": stat["mulligan_sum"] / stat["sample"] if stat["sample"] else None,
                         "sample": stat["sample"]})
        synced = {r["member_id"] for r in coverage if r["last_sync"] is not None}
        return {"period": period, "rows": rows, "catalog_updated": catalog["imported_at"],
                "synced": len(set(names) & synced), "members": len(names), "projection_pending": pending}

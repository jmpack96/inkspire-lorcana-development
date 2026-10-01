"""Team Duels summary from history and compact, member-owned opening evidence."""
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select, true

from lorcana.db.schema.duels import (
    duels_connections as accounts, duels_games as games,
    duels_game_observations as observations, duels_normalizations as normalizations,
    duels_replays as replays,
)
from lorcana.duels.matchups import MatchupRepository, color_pair, current_set
from lorcana.duels.replay_parser import PARSER_VERSION


def validated_mulligan(evidence):
    """Missing, inconsistent, or warned opening evidence is not a zero."""
    if not isinstance(evidence, dict) or evidence.get("parser_warnings"):
        return None
    game = evidence.get("game") or {}
    if not isinstance(game, dict) or game.get("perspective") is None:
        return None
    names = game.get("player_names") or {}
    if names and len(names) != 2:
        return None
    initial = evidence.get("starting_hand")
    mulligan = evidence.get("mulligan")
    if not isinstance(mulligan, dict):
        return None
    kept, sent, drawn = (mulligan.get(k) for k in ("kept", "sent_back", "drawn"))
    count = mulligan.get("count")
    if not (type(count) is int and 0 <= count <= 7
            and all(isinstance(group, list) and
                    all(isinstance(card, dict) and isinstance(card.get("id"), str) and card["id"]
                        for card in group) for group in (initial, kept, sent, drawn))):
        return None
    if not (len(initial) == 7 and len(sent) == len(drawn) == count and len(kept) + count == 7
            and Counter(c["id"] for c in initial) == Counter(c["id"] for c in kept + sent)):
        return None
    return count


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
        ).subquery()
        # Fetch only opening evidence, not full replays/actions/private hands for display.
        opening = select(func.jsonb_build_object(
            "game", normalizations.c.normalized["game"],
            "starting_hand", normalizations.c.normalized["starting_hand"],
            "mulligan", normalizations.c.normalized["mulligan"],
            "parser_warnings", normalizations.c.normalized["parser_warnings"],
        ).label("evidence")).select_from(replays.join(normalizations)).where(
            replays.c.game_id == latest.c.game_id,
            replays.c.connection_id == latest.c.connection_id,
            replays.c.status == "valid", normalizations.c.status == "valid",
            normalizations.c.parser_version == PARSER_VERSION,
        ).order_by(replays.c.fetched_at.desc(), normalizations.c.created_at.desc(),
                   normalizations.c.normalization_id).limit(1).lateral()
        query = select(latest, opening.c.evidence).select_from(latest.outerjoin(opening, true()))
        # Stream the complete period in batches; no arbitrary history/replay cap.
        return connection.execution_options(yield_per=500).execute(query).mappings()


class DuelsSummaryService:
    def __init__(self, *, repository, connection_factory, team_slug,
                 clock=lambda: datetime.now(timezone.utc)):
        self.repository, self.connection_factory = repository, connection_factory
        self.team_slug, self.clock = team_slug, clock

    @classmethod
    def from_engine(cls, engine, *, team_slug):
        return cls(repository=DuelsSummaryRepository(), connection_factory=engine.connect,
                   team_slug=team_slug)

    def report(self, viewer_id):
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
            stats = defaultdict(lambda: {"games": 0, "colors": Counter(), "mulligan_sum": 0, "sample": 0})
            for row in self.repository.history(connection, member_ids=list(names),
                                               since=period["start"], until=now):
                member = row["member_id"]
                if member not in names:
                    continue
                stat = stats[member]
                stat["games"] += 1
                colors = color_pair(row["your_deck_colors"])
                if colors != "Unknown":
                    stat["colors"][colors] += 1
                mulligan = validated_mulligan(row["evidence"])
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
                "synced": len(set(names) & synced), "members": len(names)}

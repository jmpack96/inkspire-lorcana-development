"""Current-set team matchup results from history only; no AI or replay access."""
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
import re
from uuid import UUID

from sqlalchemy import func, select

from lorcana.db.schema.catalog import catalog_snapshots
from lorcana.db.schema.duels import duels_connections as accounts, duels_games as games, duels_game_observations as observations
from lorcana.db.schema.identity import members, teams, team_memberships, discord_accounts

COLORS = ("Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel")
COLOR_PAIRS = tuple("/".join(pair) for pair in combinations(COLORS, 2))


def color_pair(value):
    if not isinstance(value, list) or not value:
        return "Unknown"
    names = {str(c).strip().title() for c in value}
    if not names.issubset(COLORS):
        return "Unknown"
    return "/".join(c for c in COLORS if c in names)


def current_set(metadata, now):
    """Numeric expansion codes only; future releases/promotional sets are excluded."""
    candidates = []
    for item in (metadata or {}).get("sets", []):
        code = str(item.get("code") or "")
        if not code.isdecimal() or int(code) <= 0 or not item.get("name"):
            continue
        try:
            start = datetime.fromisoformat(str(item["released_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        start = start.astimezone(timezone.utc)
        if start <= now:
            candidates.append((start, int(code), str(item["name"])))
    if not candidates:
        raise ValueError("Set release dates are unavailable. Ask an administrator to run `lorcana catalog-enqueue-refresh` and let the worker finish, then try again.")
    start, code, name = max(candidates)
    return {"name": name, "code": code, "start": start}


def queue_label(row):
    name = row.get("queue_name") or row.get("queue_id") or row.get("mode") or "Unknown queue"
    evidence = f"{row.get('queue_id') or ''} {row.get('queue_name') or ''}".lower()
    tokens = set(re.findall(r"[a-z]+", evidence))
    format_name = "Infinity" if "infinity" in tokens and "core" not in tokens else "Core" if "core" in tokens and "infinity" not in tokens else "Format unknown"
    ranked = {True: "ranked", False: "unranked", None: "rank unknown"}[row.get("ranked")]
    return f"{format_name} · {name} · {row.get('match_format') or 'match format unknown'} · {ranked}"


class MatchupRepository:
    def roster(self, connection, slug, *, duels_only=False):
        query = select(
            members.c.member_id, members.c.preferred_display_name,
        ).select_from(members.join(team_memberships).join(teams)).where(
            teams.c.slug == slug, teams.c.status == "active", members.c.status == "active",
            team_memberships.c.ended_at.is_(None),
        ).order_by(members.c.preferred_display_name, members.c.member_id)
        if duels_only:
            # Worker-owned secrets are not available to the bot. A configured
            # connection is the durable indication that this member uses Duels.
            # EXISTS avoids duplicating members with multiple connections.
            query = query.where(select(accounts.c.connection_id).where(
                accounts.c.member_id == members.c.member_id,
                accounts.c.status.in_(("active", "auth_error")),
                func.btrim(accounts.c.credential_ref).like("env:%"),
                func.length(func.btrim(func.substr(func.btrim(accounts.c.credential_ref), 5))) > 0,
            ).exists())
        return [dict(r) for r in connection.execute(query).mappings()]

    def viewer(self, connection, discord_user_id):
        return connection.scalar(select(discord_accounts.c.member_id).where(
            discord_accounts.c.discord_user_id == discord_user_id))

    def catalog(self, connection):
        return connection.execute(select(catalog_snapshots.c.metadata_json, catalog_snapshots.c.imported_at)
            .order_by(catalog_snapshots.c.imported_at.desc(), catalog_snapshots.c.snapshot_id).limit(1)).mappings().one_or_none()

    def coverage(self, connection, member_ids):
        return [dict(r) for r in connection.execute(select(
            accounts.c.member_id, func.max(accounts.c.last_sync_completed_at).label("last_sync"),
        ).where(accounts.c.member_id.in_(member_ids)).group_by(accounts.c.member_id)).mappings()]

    def results(self, connection, *, member_ids, since, until):
        # First deduplicate accounts per member/game. Keep team-v-team games out
        # of external matchup records, even for a single selected player.
        unique = select(
            accounts.c.member_id, observations.c.game_id, observations.c.result,
            observations.c.your_deck_colors, observations.c.opponent_deck_colors,
            games.c.queue_id, games.c.queue_name, games.c.mode, games.c.match_format, games.c.ranked,
        ).select_from(observations.join(accounts).join(games)).where(
            accounts.c.member_id.in_(member_ids), games.c.started_at >= since, games.c.started_at <= until,
        ).distinct(accounts.c.member_id, observations.c.game_id).order_by(
            accounts.c.member_id, observations.c.game_id, observations.c.last_seen_at.desc(), observations.c.connection_id,
        ).subquery()
        counted = select(unique, func.count().over(partition_by=unique.c.game_id).label("team_observers")).subquery()
        columns = [counted.c[k] for k in ("member_id", "result", "your_deck_colors", "opponent_deck_colors",
                                        "queue_id", "queue_name", "mode", "match_format", "ranked", "team_observers")]
        return [dict(r) for r in connection.execute(
            select(*columns, func.count().label("games")).group_by(*columns)
        ).mappings()]


class MatchupService:
    def __init__(self, *, repository, connection_factory, team_slug, clock=lambda: datetime.now(timezone.utc)):
        self.repository, self.connection_factory = repository, connection_factory
        self.team_slug, self.clock = team_slug, clock

    @classmethod
    def from_engine(cls, engine, *, team_slug):
        return cls(repository=MatchupRepository(), connection_factory=engine.connect, team_slug=team_slug)

    def _authorized_roster(self, connection, viewer_id):
        roster = self.repository.roster(connection, self.team_slug)
        viewer = self.repository.viewer(connection, viewer_id)
        if viewer not in {r["member_id"] for r in roster}:
            raise ValueError("Link your Discord account to an active member of this team to view matchup results.")
        return roster, viewer

    def choices(self, viewer_id):
        with self.connection_factory() as connection:
            self._authorized_roster(connection, viewer_id)
            roster = self.repository.roster(connection, self.team_slug, duels_only=True)
        return roster

    def report(self, viewer_id, *, team=False, player=None, opponent=None):
        if opponent is not None and opponent not in COLOR_PAIRS:
            raise ValueError("Choose an opponent color combination from the dropdown.")
        now = self.clock()
        with self.connection_factory() as connection:
            roster, viewer = self._authorized_roster(connection, viewer_id)
            all_names = {r["member_id"]: r["preferred_display_name"] for r in roster}
            duels_roster = self.repository.roster(connection, self.team_slug, duels_only=True)
            names = {r["member_id"]: r["preferred_display_name"] for r in duels_roster}
            try:
                selected = None if team else UUID(player) if player else viewer
            except (TypeError, ValueError):
                raise ValueError("Select a player from the team dropdown.") from None
            if selected is not None and selected not in all_names:
                raise ValueError("That player is not an active member of this team.")
            if selected is not None and selected not in names:
                raise ValueError("That player has no configured Duels connection. Choose a player from the dropdown.")
            catalog = self.repository.catalog(connection)
            period = current_set(catalog["metadata_json"] if catalog else {}, now)
            coverage = self.repository.coverage(connection, list(names))
            # Retain the full roster for recognizing team-v-team games, even
            # when one member's connection has since been disabled.
            results = self.repository.results(connection, member_ids=list(all_names), since=period["start"], until=now)
        grouped = defaultdict(lambda: {"win": 0, "loss": 0, "draw": 0, "unknown": 0})
        internal = 0
        for r in results:
            if r["member_id"] not in names:
                continue
            if selected is not None and r["member_id"] != selected:
                continue
            ours, theirs = color_pair(r["your_deck_colors"]), color_pair(r["opponent_deck_colors"])
            if opponent is not None and theirs != opponent:
                continue
            if r["team_observers"] > 1:
                internal += r["games"]
                continue
            # Pool team members for team reports; retain exact queue identity.
            key = (None if team else r["member_id"], ours, theirs, r.get("queue_id"), r.get("queue_name"),
                   r.get("mode"), r.get("match_format"), r.get("ranked"))
            outcome = str(r["result"] or "").strip().lower()
            outcome = {"won": "win", "lost": "loss", "tie": "draw"}.get(outcome, outcome)
            grouped[key][outcome if outcome in {"win", "loss", "draw"} else "unknown"] += r["games"]
        rows = []
        for key, counts in grouped.items():
            member, ours, theirs, queue_id, queue_name, mode, match_format, ranked = key
            rows.append({**({"player": names[member]} if not team else {}),
                         "ours": ours, "theirs": theirs, **counts,
                         "queue": queue_label(dict(queue_id=queue_id, queue_name=queue_name, mode=mode,
                                                    match_format=match_format, ranked=ranked))})
        rows.sort(key=lambda r: (-sum(r[k] for k in ("win", "loss", "draw", "unknown")), r.get("player", ""), r["ours"], r["theirs"], r["queue"]))
        expected = set(names) if team else {selected}
        linked = {r["member_id"] for r in coverage if r["member_id"] in expected}
        synced = {r["member_id"] for r in coverage if r["member_id"] in expected and r["last_sync"] is not None}
        return {"title": "Team matchups" if team else f"{names[selected]} — matchups",
                "period": period, "catalog_updated": catalog["imported_at"], "opponent": opponent,
                "rows": rows, "team": team, "members": len(expected), "linked": len(linked), "synced": len(synced),
                "internal": internal, "missing": [names[m] for m in expected - synced]}

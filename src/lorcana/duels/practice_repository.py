"""Member-scoped, read-only practice queries. No feature backfill is required."""
from sqlalchemy import func, select, true

from lorcana.db.schema.duels import (
    duels_connections as connections, duels_games as games,
    duels_game_observations as observations, duels_normalizations as normalizations,
    duels_replays as replays,
)
from lorcana.duels.replay_parser import PARSER_VERSION


class PracticeRepository:
    def history(self, connection, *, member_id, since, until, ranked, limit):
        # Deduplicate accounts belonging to the same member before limiting.
        query = select(
            observations.c.game_id, observations.c.connection_id, observations.c.result,
            observations.c.went_first, observations.c.your_deck_colors,
            observations.c.opponent_deck_colors, games.c.started_at,
            games.c.ranked, games.c.queue_name, games.c.mode, games.c.match_format,
        ).select_from(observations.join(connections).join(games)).where(
            connections.c.member_id == member_id,
            games.c.started_at >= since, games.c.started_at <= until,
        )
        if ranked is not None:
            query = query.where(games.c.ranked == ranked)
        latest = query.distinct(observations.c.game_id).order_by(
            observations.c.game_id, observations.c.last_seen_at.desc(), observations.c.connection_id,
        ).subquery()
        bounded = select(latest).order_by(latest.c.started_at.desc(), latest.c.game_id).limit(limit).subquery()
        # Latest valid normalization for exactly this member/account perspective.
        evidence = select(
            normalizations.c.normalization_id,
            normalizations.c.normalized["decklist"].label("decklist"),
        ).select_from(replays.join(normalizations)).where(
            replays.c.connection_id == bounded.c.connection_id,
            replays.c.game_id == bounded.c.game_id,
            replays.c.status == "valid", normalizations.c.status == "valid",
            normalizations.c.parser_version == PARSER_VERSION,
        ).order_by(replays.c.fetched_at.desc(), normalizations.c.created_at.desc(),
                   normalizations.c.normalization_id).limit(1).lateral()
        return [dict(row) for row in connection.execute(
            select(bounded, evidence.c.normalization_id, evidence.c.decklist)
            .select_from(bounded.outerjoin(evidence, true()))
            .order_by(bounded.c.started_at.desc(), bounded.c.game_id)
        ).mappings()]

    def opening_evidence(self, connection, *, member_id, normalization_ids):
        if not normalization_ids:
            return {}
        # Repeat the ownership check; caller-supplied IDs are not authorization.
        rows = connection.execute(select(
            normalizations.c.normalization_id,
            func.jsonb_build_object(
                "game", normalizations.c.normalized["game"],
                "starting_hand", normalizations.c.normalized["starting_hand"],
                "mulligan", normalizations.c.normalized["mulligan"],
                "effective_actions", normalizations.c.normalized["effective_actions"],
                "parser_warnings", normalizations.c.normalized["parser_warnings"],
            ).label("normalized"),
        ).select_from(normalizations.join(replays).join(connections)).where(
            connections.c.member_id == member_id,
            normalizations.c.normalization_id.in_(normalization_ids),
            normalizations.c.parser_version == PARSER_VERSION,
            normalizations.c.status == "valid", replays.c.status == "valid",
        )).mappings()
        return {row["normalization_id"]: row["normalized"] for row in rows}

    def sync_status(self, connection, *, member_id):
        rows = connection.execute(select(connections.c.status, connections.c.last_sync_completed_at)
                                  .where(connections.c.member_id == member_id)).mappings().all()
        completed = [r["last_sync_completed_at"] for r in rows if r["last_sync_completed_at"]]
        return {"connections": len(rows), "last_sync": max(completed) if completed else None,
                "attention": sum(r["status"] != "active" for r in rows)}

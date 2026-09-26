"""Inspect a bounded coach request without creating jobs or making model calls."""
import argparse
import json
from uuid import UUID

from sqlalchemy import text
from lorcana.bootstrap import ApplicationResources
from lorcana.catalog.repository import CatalogRepository
from lorcana.coach.service import CoachService
from lorcana.coach.grounding import incomplete_card_ids
from lorcana.coach.rules import load_bundle, for_game
from lorcana.coach.openai_analyzer import OpenAIResponsesCoachAnalyzer
from lorcana.coach.review_plan import prepare_review, request_budget, ReviewBlocked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--connection-id", required=True, type=UUID)
    parser.add_argument("--turn", action="append", type=int)
    args = parser.parse_args()
    resources = ApplicationResources.from_env()
    try:
        with resources.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT c.member_id, n.normalization_id, f.feature_set_id
                FROM duels_replays r JOIN duels_connections c USING (connection_id)
                JOIN duels_normalizations n USING (replay_id)
                JOIN duels_feature_sets f USING (normalization_id)
                WHERE r.game_id = :game AND r.connection_id = :connection
                  AND r.status = 'valid' AND n.status = 'valid'
                ORDER BY r.fetched_at DESC, n.created_at DESC, f.created_at DESC LIMIT 1
            """), {"game": args.game_id, "connection": args.connection_id}).mappings().one_or_none()
            snapshot = CatalogRepository().latest_snapshot(conn)
        if row is None or snapshot is None:
            raise ReviewBlocked("Processed replay or catalog snapshot unavailable")
        evidence = CoachService.from_engine(resources.engine)._evidence_package(
            member_id=row["member_id"], normalization_id=row["normalization_id"],
            feature_set_id=row["feature_set_id"], catalog_snapshot_id=snapshot["snapshot_id"], decklist_id=None)
        evidence["rules"] = for_game(load_bundle(resources.settings.coach_rules_bundle), evidence.get("played_at"))
        selected = prepare_review(evidence, args.turn)
        incomplete = incomplete_card_ids(selected["catalog"]["facts"])
        if incomplete:
            raise ReviewBlocked("Incomplete selected card facts: " + ", ".join(incomplete))
        analyzer = OpenAIResponsesCoachAnalyzer(api_key="offline-preview-no-api-call", model=resources.settings.openai_coach_model)
        try:
            budget = request_budget(analyzer.request_body(selected))
        finally:
            analyzer.close()
        print(json.dumps({"game_id": args.game_id, "scope": selected["review_scope"],
            "recorded_statistics": selected["recorded_statistics"],
            "duration_facts": selected["duration_facts"],
            "selected_card_ids": sorted(selected["catalog"]["facts"]),
            "selected_rule_pages": sorted(selected["rules"]["citations"]),
            "budget": budget, "paid_calls": 0}, indent=2))
    except ReviewBlocked as error:
        parser.exit(2, "Preview blocked; no paid call made: " + str(error) + "\n")
    finally:
        resources.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text

from lorcana.catalog.service import CatalogService
from lorcana.coach.service import CoachAccessError, CoachError, CoachService
from lorcana.coach.types import CoachAnalyzerResult, CoachFindingDraft
from lorcana.db.schema.coach import coach_analysis_runs, coach_findings
from lorcana.db.schema.duels import (
    duels_connections,
    duels_feature_sets,
    duels_games,
    duels_normalizations,
    duels_replays,
)
from lorcana.db.schema.identity import members

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 13, 21, 0, tzinfo=timezone.utc)


class FakeAnalyzer:
    provider = "fake"
    model = "fixture-v1"
    prompt_version = "coach-v1"

    def __init__(self, action_id: int = 4):
        self.action_id = action_id
        self.calls = 0

    def analyze(self, evidence):
        self.calls += 1
        assert "actions" not in evidence["normalization"]
        assert [a["seq"] for a in evidence["normalization"]["effective_actions"]] == [1, 4]
        assert evidence["catalog"]["facts"]["12-11"]["name"] == "Hamm - Piggy Bank"
        return CoachAnalyzerResult(
            summary="Evidence-based game review.",
            findings=(
                CoachFindingDraft(
                    category="sequencing",
                    impact="medium",
                    confidence=0.92,
                    claim_type="inference",
                    observation="The turn-two line can be improved.",
                    recommendation="Evaluate the alternate sequence before questing.",
                    evidence_action_ids=(self.action_id,),
                    evidence_turns=(2,),
                ),
            ),
            usage={"input_tokens": 123, "output_tokens": 45},
        )


def _clear(engine):
    with engine.begin() as connection:
        connection.execute(text(
            "TRUNCATE TABLE "
            "coach_reports, coach_findings, coach_analysis_runs, decklist_cards, decklists, "
            "catalog_cards, catalog_snapshots, duels_feature_sets, duels_normalizations, "
            "duels_replays, duels_game_observations, duels_games, duels_connections, members CASCADE"
        ))


def _seed_evidence(engine):
    member_id = uuid4()
    other_member_id = uuid4()
    connection_id = uuid4()
    replay_id = uuid4()
    normalization_id = uuid4()
    feature_set_id = uuid4()
    game_id = "coach-game-1"
    with engine.begin() as connection:
        connection.execute(insert(members), [
            dict(member_id=member_id, preferred_display_name="Coach User", status="active", created_at=NOW, updated_at=NOW),
            dict(member_id=other_member_id, preferred_display_name="Other User", status="active", created_at=NOW, updated_at=NOW),
        ])
        connection.execute(insert(duels_connections).values(
            connection_id=connection_id,
            member_id=member_id,
            credential_ref="env:DUELS_TEST_TOKEN",
            status="active",
            history_exhausted=True,
            created_at=NOW,
            updated_at=NOW,
        ))
        connection.execute(insert(duels_games).values(
            game_id=game_id,
            first_seen_at=NOW,
            last_seen_at=NOW,
        ))
        connection.execute(insert(duels_replays).values(
            replay_id=replay_id,
            game_id=game_id,
            connection_id=connection_id,
            provider_replay_id="provider-replay",
            perspective=1,
            fetched_at=NOW,
            source_sha256="a" * 64,
            content_encoding="gzip",
            compressed_bytes=b"fixture",
            compressed_size=7,
            status="valid",
            validation={},
        ))
        connection.execute(insert(duels_normalizations).values(
            normalization_id=normalization_id,
            replay_id=replay_id,
            parser_version="parser-v1",
            schema_version=3,
            normalized={
                "game": {"perspective_player": 1},
                "decklist": [],
                "mulligan": {},
                "undo_ranges": [{"from_seq": 3, "to_seq": 3}],
                "actions": [
                    {"seq": 1, "gameplay_turn": 1},
                    {"seq": 3, "gameplay_turn": 1, "undone": True},
                    {"seq": 4, "gameplay_turn": 2},
                ],
                "effective_actions": [
                    {"seq": 1, "gameplay_turn": 1, "type": "play", "card_id": "12-11", "card_name": "Hamm - Piggy Bank"},
                    {"seq": 4, "gameplay_turn": 2, "type": "quest", "card_id": "10-55", "card_name": "Demona"},
                ],
                "final_state": {"winner": 1},
                "parser_warnings": [],
            },
            normalized_sha256="b" * 64,
            warnings=[],
            status="valid",
            created_at=NOW,
        ))
        connection.execute(insert(duels_feature_sets).values(
            feature_set_id=feature_set_id,
            normalization_id=normalization_id,
            extractor_version="features-v1",
            features={"perspective_action_count": 2},
            features_sha256="c" * 64,
            created_at=NOW,
        ))
    return member_id, other_member_id, normalization_id, feature_set_id


def test_coach_end_to_end_is_persisted_cached_and_access_controlled(db_engine):
    _clear(db_engine)
    try:
        member_id, other_member_id, normalization_id, feature_set_id = _seed_evidence(db_engine)
        catalog = CatalogService.from_engine(db_engine, clock=lambda: NOW).import_snapshot(
            {
                "cards": [
                    {"id": "12-11", "name": "Hamm - Piggy Bank", "colors": ["Sapphire"], "cost": 2, "inkable": True},
                    {"id": "10-55", "name": "Demona", "colors": ["Sapphire"], "cost": 6, "inkable": True},
                ]
            },
            source_name="integration-fixture",
            source_version="v1",
        )
        analyzer = FakeAnalyzer()
        coach = CoachService.from_engine(db_engine, clock=lambda: NOW)

        first = coach.analyze(
            member_id=member_id,
            normalization_id=normalization_id,
            feature_set_id=feature_set_id,
            catalog_snapshot_id=catalog.snapshot_id,
            analyzer=analyzer,
        )
        assert first.cached is False
        assert first.finding_count == 1
        assert analyzer.calls == 1

        second = coach.analyze(
            member_id=member_id,
            normalization_id=normalization_id,
            feature_set_id=feature_set_id,
            catalog_snapshot_id=catalog.snapshot_id,
            analyzer=analyzer,
        )
        assert second.cached is True
        assert second.analysis_run_id == first.analysis_run_id
        assert second.finding_count == 1
        assert analyzer.calls == 1

        loaded = coach.report(member_id, first.analysis_run_id)
        assert loaded is not None
        assert loaded.content == first.content
        assert coach.report(other_member_id, first.analysis_run_id) is None

        with pytest.raises(CoachAccessError):
            coach.analyze(
                member_id=other_member_id,
                normalization_id=normalization_id,
                feature_set_id=feature_set_id,
                catalog_snapshot_id=catalog.snapshot_id,
                analyzer=analyzer,
            )

        with db_engine.connect() as connection:
            assert connection.execute(select(coach_analysis_runs.c.status)).scalar_one() == "succeeded"
            finding = connection.execute(select(coach_findings)).mappings().one()
            assert finding["evidence_action_ids"] == [4]
    finally:
        _clear(db_engine)


def test_coach_rejects_undone_action_reference_and_persists_failure(db_engine):
    _clear(db_engine)
    try:
        member_id, _, normalization_id, feature_set_id = _seed_evidence(db_engine)
        catalog = CatalogService.from_engine(db_engine, clock=lambda: NOW).import_snapshot(
            {"cards": [{"id": "12-11", "name": "Hamm - Piggy Bank"}, {"id": "10-55", "name": "Demona"}]},
            source_name="integration-fixture",
        )
        coach = CoachService.from_engine(db_engine, clock=lambda: NOW)
        with pytest.raises(CoachError, match="effective replay evidence"):
            coach.analyze(
                member_id=member_id,
                normalization_id=normalization_id,
                feature_set_id=feature_set_id,
                catalog_snapshot_id=catalog.snapshot_id,
                analyzer=FakeAnalyzer(action_id=3),
            )
        with db_engine.connect() as connection:
            row = connection.execute(select(coach_analysis_runs)).mappings().one()
            assert row["status"] == "failed"
            assert row["error_category"] == "CoachError"
    finally:
        _clear(db_engine)

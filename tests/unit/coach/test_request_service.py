from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from lorcana.coach.request_service import CoachRequestError, CoachRequestService

MEMBER = UUID("00000000-0000-0000-0000-000000000a01")
NORMALIZATION = UUID("00000000-0000-0000-0000-000000000a02")
FEATURES = UUID("00000000-0000-0000-0000-000000000a03")
CATALOG = UUID("00000000-0000-0000-0000-000000000a04")
JOB = UUID("00000000-0000-0000-0000-000000000a05")


class Duels:
    evidence = SimpleNamespace(
        game_id="game-1",
        normalization_id=NORMALIZATION,
        feature_set_id=FEATURES,
    )

    def latest_evidence_for_game(self, member_id, game_id):
        assert member_id == MEMBER
        return self.evidence if game_id == "game-1" else None


class Catalog:
    snapshot = CATALOG

    def latest_snapshot_id(self):
        return self.snapshot


class Jobs:
    def __init__(self):
        self.call = None

    def enqueue(self, kind, **kwargs):
        self.call = (kind, kwargs)
        return SimpleNamespace(job_id=JOB, created=True)


def test_request_pins_replay_features_catalog_and_analyzer_generation():
    jobs = Jobs()
    service = CoachRequestService(
        duels=Duels(),
        catalog=Catalog(),
        jobs=jobs,
        analyzer_name="Primary",
        analyzer_generation="prompt-2026-09",
    )
    result = service.request(
        member_id=MEMBER,
        game_id="game-1",
        analysis_config={"focus": "sequencing"},
    )
    assert result.job_id == JOB
    assert result.normalization_id == NORMALIZATION
    assert result.feature_set_id == FEATURES
    assert result.catalog_snapshot_id == CATALOG
    _, values = jobs.call
    assert values["payload"]["analyzer_name"] == "primary"
    assert values["payload"]["analyzer_generation"] == "prompt-2026-09"


def test_request_requires_coach_ready_replay_and_catalog():
    service = CoachRequestService(
        duels=Duels(), catalog=Catalog(), jobs=Jobs(), analyzer_name="primary"
    )
    with pytest.raises(CoachRequestError, match="replay evidence"):
        service.request(member_id=MEMBER, game_id="missing")

    catalog = Catalog()
    catalog.snapshot = None
    service = CoachRequestService(
        duels=Duels(), catalog=catalog, jobs=Jobs(), analyzer_name="primary"
    )
    with pytest.raises(CoachRequestError, match="catalog"):
        service.request(member_id=MEMBER, game_id="game-1")

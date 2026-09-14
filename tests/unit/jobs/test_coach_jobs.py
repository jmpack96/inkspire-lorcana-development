from __future__ import annotations

from uuid import UUID

import pytest

from lorcana.jobs.kinds import COACH_ANALYZE_REPLAY, enqueue_coach_analysis

MEMBER = UUID("00000000-0000-0000-0000-000000000901")
NORMALIZATION = UUID("00000000-0000-0000-0000-000000000902")
FEATURES = UUID("00000000-0000-0000-0000-000000000903")
CATALOG = UUID("00000000-0000-0000-0000-000000000904")


class Queue:
    def __init__(self):
        self.calls = []

    def enqueue(self, kind, **kwargs):
        self.calls.append((kind, kwargs))
        return type("Result", (), {"job_id": UUID(int=1), "created": True})()


def test_enqueue_coach_analysis_is_deterministic_and_never_contains_credentials():
    queue = Queue()
    enqueue_coach_analysis(
        queue,
        member_id=MEMBER,
        normalization_id=NORMALIZATION,
        feature_set_id=FEATURES,
        catalog_snapshot_id=CATALOG,
        analyzer_name=" Primary ",
        analysis_config={"focus": "sequencing"},
    )
    enqueue_coach_analysis(
        queue,
        member_id=MEMBER,
        normalization_id=NORMALIZATION,
        feature_set_id=FEATURES,
        catalog_snapshot_id=CATALOG,
        analyzer_name="primary",
        analysis_config={"focus": "sequencing"},
    )
    first_kind, first = queue.calls[0]
    second_kind, second = queue.calls[1]
    assert first_kind == second_kind == COACH_ANALYZE_REPLAY
    assert first["idempotency_key"] == second["idempotency_key"]
    assert first["payload"]["analyzer_name"] == "primary"
    assert "token" not in str(first["payload"]).lower()
    assert first["max_attempts"] == 3


def test_enqueue_coach_analysis_rejects_blank_analyzer_name():
    with pytest.raises(ValueError, match="analyzer_name"):
        enqueue_coach_analysis(
            Queue(),
            member_id=MEMBER,
            normalization_id=NORMALIZATION,
            feature_set_id=FEATURES,
            catalog_snapshot_id=CATALOG,
            analyzer_name="  ",
        )

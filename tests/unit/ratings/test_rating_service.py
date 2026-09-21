from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from lorcana.ratings.policy import GlobalEloV1Policy, LegacyParityPolicy
from lorcana.ratings.service import RatingBuildError, RatingService, ordered_input_digest
from lorcana.ratings.types import RatingCandidate, RatingRunInput

NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)
RUN_ID = UUID("00000000-0000-0000-0000-000000000101")


def candidate(match_id: int, *, p1: int = 1, p2: int = 2, winner: int | None = 1, draw: bool = False,
              state: str = "complete") -> RatingCandidate:
    return RatingCandidate(
        match_id=match_id,
        event_id=10,
        round_id=100 + match_id,
        player1_id=p1,
        player2_id=p2,
        winner_id=winner,
        is_draw=draw,
        match_status="COMPLETE",
        is_bye=False,
        is_ghost_match=False,
        participant_count=2,
        event_start_datetime=NOW + timedelta(minutes=match_id),
        event_format="Core Constructed",
        event_sync_state=state,
        phase_order=0,
        round_number=match_id,
    )


class FakeRepository:
    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.runs = {}
        self.inputs = {}
        self.history = {}
        self.current = {}
        self.publications = {}
        self.fail_calculation = False

    def create_run(self, _c, **values):
        self.runs[values["rating_run_id"]] = {**values, "status": "building"}

    def iter_candidates(self, _c):
        yield from self.candidates

    def insert_run_inputs(self, _c, run_id, rows):
        self.inputs.setdefault(run_id, []).extend(rows)

    def finish_snapshot(self, _c, **values):
        self.runs[values["rating_run_id"]].update(values)

    def iter_run_inputs(self, _c, run_id):
        if self.fail_calculation:
            raise RuntimeError("calculation reader failed")
        yield from self.inputs.get(run_id, [])

    def insert_history(self, _c, rows):
        for row in rows:
            self.history[(row["rating_run_id"], row["sequence_number"], row["player_id"])] = dict(row)

    def insert_current(self, _c, rows):
        for row in rows:
            self.current[(row["rating_run_id"], row["player_id"])] = dict(row)

    def count_history(self, _c, run_id):
        return sum(key[0] == run_id for key in self.history)

    def count_current(self, _c, run_id):
        return sum(key[0] == run_id for key in self.current)

    def mark_validated(self, _c, **values):
        self.runs[values["rating_run_id"]].update(values, status="validated")

    def mark_failed(self, _c, **values):
        self.runs[values["rating_run_id"]].update(values, status="failed")

    def get_run_status(self, _c, run_id, *, for_update=False):
        row = self.runs.get(run_id)
        return None if row is None else row["status"]

    def publish(self, _c, **values):
        name = values["publication_name"]
        new_run = values["rating_run_id"]
        existing = self.publications.get(name)
        if existing is None:
            self.publications[name] = {"current": new_run, "previous": None}
        elif existing["current"] != new_run:
            self.publications[name] = {"current": new_run, "previous": existing["current"]}
        self.runs[new_run]["status"] = "published"

    def resolve_publication(self, _c, publication_name):
        publication = self.publications.get(publication_name)
        if publication is None:
            return None
        run_id = publication["current"]
        row = self.runs[run_id]
        return {
            "publication_name": publication_name,
            "rating_run_id": run_id,
            "algorithm": row["algorithm"],
            "algorithm_version": row["algorithm_version"],
            "policy_version": row["policy_version"],
            "parameters": row["parameters"],
            "input_count": row["input_count"],
            "player_count": row["player_count"],
            "ordered_input_digest": row["ordered_input_digest"],
            "exclusion_counts": row.get("exclusion_counts") or {},
        }

    def prune_unretained_runs(self, _c):
        retained = set()
        for publication in self.publications.values():
            retained.add(publication["current"])
            if publication["previous"] is not None:
                retained.add(publication["previous"])
        doomed = tuple(
            run_id for run_id, row in self.runs.items()
            if run_id not in retained and row["status"] != "building"
        )
        for run_id in doomed:
            self.runs.pop(run_id, None)
            self.inputs.pop(run_id, None)
            self.history = {key: value for key, value in self.history.items() if key[0] != run_id}
            self.current = {key: value for key, value in self.current.items() if key[0] != run_id}
        return doomed


@contextmanager
def fake_context():
    yield object()


def service(repository, *, policy=None):
    return RatingService(
        repository=repository,
        read_connection_factory=fake_context,
        transaction_factory=fake_context,
        policy=policy or GlobalEloV1Policy(),
        clock=lambda: NOW,
        uuid_factory=lambda: RUN_ID,
        input_batch_size=1,
        history_batch_size=2,
    )


def test_build_snapshots_facts_calculates_and_validates():
    repo = FakeRepository([
        candidate(1),
        candidate(2, p1=2, p2=3, winner=3),
        candidate(3, p1=1, p2=3, winner=None, draw=True),
        candidate(4, state="partial"),
    ])
    result = service(repo).build(notes="test")

    assert result.status == "validated"
    assert result.input_count == 3
    assert result.player_count == 3
    assert result.exclusion_counts == {"event_not_complete": 1}
    assert repo.runs[RUN_ID]["algorithm_version"] == "elo_v2_2player_only"
    assert repo.runs[RUN_ID]["policy_version"] == "global_elo_v1"
    assert len(repo.history) == 6
    assert len(repo.current) == 3
    assert repo.current[(RUN_ID, 1)]["matches_played"] == 2
    assert repo.runs[RUN_ID]["status"] == "validated"


def test_legacy_policy_includes_partial_source_event():
    repo = FakeRepository([candidate(1, state="partial")])
    result = service(repo, policy=LegacyParityPolicy()).build()
    assert result.input_count == 1
    assert result.exclusion_counts == {}


def test_digest_covers_calculation_facts_and_order():
    a = RatingRunInput(1, 1, 10, NOW, 0, 1, 1, 2, 1, False)
    b = RatingRunInput(2, 2, 10, NOW, 0, 2, 2, 3, 3, False)
    assert ordered_input_digest([a, b]) == ordered_input_digest([a, b])
    assert ordered_input_digest([a, b]) != ordered_input_digest([b, a])
    changed = RatingRunInput(1, 1, 10, NOW, 0, 1, 1, 2, 2, False)
    assert ordered_input_digest([a]) != ordered_input_digest([changed])


def test_failed_calculation_marks_run_failed_and_never_publishes():
    repo = FakeRepository([candidate(1)])
    repo.fail_calculation = True
    rating_service = service(repo)

    with pytest.raises(RuntimeError, match="calculation reader failed"):
        rating_service.build_and_publish()

    assert RUN_ID not in repo.runs
    assert RUN_ID not in repo.inputs
    assert repo.publications == {}


def test_publish_rejects_building_or_missing_run():
    repo = FakeRepository([])
    repo.runs[RUN_ID] = {"status": "building"}
    rating_service = service(repo)
    with pytest.raises(RatingBuildError, match="only validated"):
        rating_service.publish(RUN_ID)
    with pytest.raises(RatingBuildError, match="does not exist"):
        rating_service.publish(UUID("00000000-0000-0000-0000-000000000999"))


def test_build_and_publish_moves_pointer_only_after_validation():
    repo = FakeRepository([candidate(1)])
    result = service(repo).build_and_publish(published_by="test-suite")
    assert result.status == "published"
    assert result.publication_name == "global_elo"
    assert repo.publications["global_elo"]["current"] == RUN_ID
    assert repo.runs[RUN_ID]["status"] == "published"


def test_publication_retains_only_current_and_previous_completed_runs():
    first = UUID("00000000-0000-0000-0000-000000000201")
    second = UUID("00000000-0000-0000-0000-000000000202")
    third = UUID("00000000-0000-0000-0000-000000000203")
    repo = FakeRepository([])
    rating_service = service(repo)

    repo.runs[first] = {"status": "validated"}
    repo.inputs[first] = [object()]
    rating_service.publish(first)
    assert repo.publications["global_elo"] == {"current": first, "previous": None}

    repo.runs[second] = {"status": "validated"}
    repo.inputs[second] = [object()]
    rating_service.publish(second)
    assert repo.publications["global_elo"] == {"current": second, "previous": first}
    assert set(repo.runs) == {first, second}

    repo.runs[third] = {"status": "validated"}
    repo.inputs[third] = [object()]
    rating_service.publish(third)
    assert repo.publications["global_elo"] == {"current": third, "previous": second}
    assert set(repo.runs) == {second, third}
    assert first not in repo.inputs

def test_republishing_current_run_keeps_previous_generation():
    first = UUID("00000000-0000-0000-0000-000000000211")
    second = UUID("00000000-0000-0000-0000-000000000212")
    repo = FakeRepository([])
    rating_service = service(repo)

    repo.runs[first] = {"status": "validated"}
    rating_service.publish(first)
    repo.runs[second] = {"status": "validated"}
    rating_service.publish(second)
    rating_service.publish(second)

    assert repo.publications["global_elo"] == {"current": second, "previous": first}
    assert set(repo.runs) == {first, second}


def test_automated_refresh_does_not_create_duplicate_run_when_source_is_unchanged():
    repo = FakeRepository([candidate(1), candidate(2)])
    first = service(repo).build_and_publish()
    assert first.status == "published"
    assert len(repo.runs) == 1

    # A subsequent scheduled refresh scans source facts, sees the exact same
    # immutable digest/policy/parameters, and reuses the current publication.
    second = service(repo).build_and_publish_if_changed()
    assert second.status == "unchanged"
    assert second.rating_run_id == first.rating_run_id
    assert len(repo.runs) == 1
    assert len(repo.inputs) == 1


def test_unchanged_refresh_still_prunes_unretained_runs():
    repo = FakeRepository([candidate(1)])
    current = service(repo).build_and_publish()
    stale = UUID("00000000-0000-0000-0000-000000000399")
    repo.runs[stale] = {"status": "failed"}
    repo.inputs[stale] = [object()]

    result = service(repo).build_and_publish_if_changed()

    assert result.status == "unchanged"
    assert result.rating_run_id == current.rating_run_id
    assert set(repo.runs) == {current.rating_run_id}
    assert stale not in repo.inputs


def test_automated_refresh_builds_new_run_when_source_changes():
    first_id = UUID("00000000-0000-0000-0000-000000000301")
    second_id = UUID("00000000-0000-0000-0000-000000000302")
    repo = FakeRepository([candidate(1)])
    ids = iter([first_id, second_id])
    rating_service = RatingService(
        repository=repo,
        read_connection_factory=fake_context,
        transaction_factory=fake_context,
        policy=GlobalEloV1Policy(),
        clock=lambda: NOW,
        uuid_factory=lambda: next(ids),
        input_batch_size=1,
        history_batch_size=2,
    )
    first = rating_service.build_and_publish()
    repo.candidates.append(candidate(2))
    second = rating_service.build_and_publish_if_changed()

    assert first.rating_run_id == first_id
    assert second.rating_run_id == second_id
    assert second.status == "published"
    assert repo.publications["global_elo"] == {"current": second_id, "previous": first_id}
    assert set(repo.runs) == {first_id, second_id}

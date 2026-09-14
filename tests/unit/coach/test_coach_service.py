from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from lorcana.coach.service import CoachAccessError, CoachError, CoachService
from lorcana.coach.types import CoachAnalyzerResult, CoachFindingDraft

NOW = datetime(2026, 9, 13, 21, 0, tzinfo=timezone.utc)
MEMBER = UUID("00000000-0000-0000-0000-000000000801")
NORMALIZATION = UUID("00000000-0000-0000-0000-000000000802")
FEATURES = UUID("00000000-0000-0000-0000-000000000803")
CATALOG = UUID("00000000-0000-0000-0000-000000000804")
RUN = UUID("00000000-0000-0000-0000-000000000805")
FINDING = UUID("00000000-0000-0000-0000-000000000806")
REPORT = UUID("00000000-0000-0000-0000-000000000807")


class FakeRepository:
    def __init__(self):
        self.runs = {}
        self.reports = {}
        self.findings = {}
        self.failed = None
        self.evidence_member = MEMBER

    def evidence(self, _c, *, member_id, normalization_id, feature_set_id):
        if member_id != self.evidence_member or normalization_id != NORMALIZATION or feature_set_id != FEATURES:
            return None
        return {
            "normalization_id": NORMALIZATION,
            "normalized": {
                "game": {"perspective_player": 1},
                "mulligan": {"cards": []},
                "undo_ranges": [{"from_seq": 3, "to_seq": 3}],
                "effective_actions": [
                    {
                        "seq": 1,
                        "gameplay_turn": 1,
                        "type": "play",
                        "actor_is_perspective": True,
                        "card_id": "12-11",
                        "card_name": "Hamm - Piggy Bank",
                    },
                    {
                        "seq": 4,
                        "gameplay_turn": 2,
                        "type": "quest",
                        "actor_is_perspective": True,
                        "card_id": "10-55",
                        "card_name": "Demona - Scourge of the Wyvern Clan",
                    },
                ],
                "actions": [
                    {"seq": 1, "gameplay_turn": 1},
                    {"seq": 3, "gameplay_turn": 1, "undone": True},
                    {"seq": 4, "gameplay_turn": 2},
                ],
                "final_state": {"winner": 1},
                "parser_warnings": [],
                "decklist": [],
            },
            "parser_version": "parser-v1",
            "normalized_sha256": "n" * 64,
            "feature_set_id": FEATURES,
            "features": {"perspective_action_count": 2},
            "extractor_version": "features-v1",
            "features_sha256": "f" * 64,
            "replay_id": UUID("00000000-0000-0000-0000-000000000808"),
            "game_id": "game-1",
        }

    def catalog_snapshot(self, _c, snapshot_id):
        if snapshot_id != CATALOG:
            return None
        return {
            "snapshot_id": CATALOG,
            "source_name": "fixture",
            "source_version": "set-12",
        }

    def catalog_facts(self, _c, snapshot_id, card_ids):
        known = {
            "12-11": {
                "card_id": "12-11", "name": "Hamm - Piggy Bank", "version": None,
                "set_code": "12", "set_name": "Set 12", "collector_number": "11",
                "ink_colors": ["sapphire"], "cost": 2, "inkable": True,
                "classifications": ["Storyborn"], "card_type": "Character", "rules_text": None,
            },
            "10-55": {
                "card_id": "10-55", "name": "Demona - Scourge of the Wyvern Clan", "version": None,
                "set_code": "10", "set_name": "Set 10", "collector_number": "55",
                "ink_colors": ["sapphire"], "cost": 6, "inkable": True,
                "classifications": [], "card_type": "Character", "rules_text": None,
            },
        }
        return [known[x] for x in sorted(set(card_ids)) if x in known]

    def decklist(self, _c, member_id, decklist_id):
        return None

    def lock_idempotency(self, _c, key):
        self.last_lock_key = key

    def run_by_idempotency(self, _c, key, *, for_update=False):
        return next((row for row in self.runs.values() if row["idempotency_key"] == key), None)

    def create_run(self, _c, **values):
        self.runs[values["analysis_run_id"]] = dict(values)
        return True

    def restart_run(self, _c, analysis_run_id, *, started_at):
        self.runs[analysis_run_id].update(status="running", started_at=started_at)
        self.findings.pop(analysis_run_id, None)
        self.reports.pop(analysis_run_id, None)

    def mark_failed(self, _c, analysis_run_id, *, completed_at, error):
        self.runs[analysis_run_id].update(
            status="failed", completed_at=completed_at,
            error_category=type(error).__name__, error_summary=str(error),
        )
        self.failed = error

    def complete(self, _c, *, analysis_run_id, findings, report_id, report_content, usage, completed_at):
        self.findings[analysis_run_id] = list(findings)
        self.reports[analysis_run_id] = {
            "report_id": report_id, "analysis_run_id": analysis_run_id,
            "member_id": MEMBER, "status": "succeeded", "content": report_content,
        }
        self.runs[analysis_run_id].update(status="succeeded", completed_at=completed_at, usage=usage)

    def report_for_run(self, _c, analysis_run_id, *, member_id=None):
        row = self.reports.get(analysis_run_id)
        if row is None or (member_id is not None and row["member_id"] != member_id):
            return None
        return row

    def finding_count(self, _c, analysis_run_id):
        return len(self.findings.get(analysis_run_id, []))

    def create_decklist(self, _c, **kwargs):
        raise NotImplementedError


@contextmanager
def connection():
    yield object()


class FakeAnalyzer:
    provider = "fake"
    model = "deterministic-v1"
    prompt_version = "coach-v1"

    def __init__(self, *, action_id=4):
        self.calls = 0
        self.action_id = action_id
        self.last_evidence = None

    def analyze(self, evidence):
        self.calls += 1
        self.last_evidence = evidence
        return CoachAnalyzerResult(
            summary="A concise evidence-based review.",
            findings=(
                CoachFindingDraft(
                    category="sequencing",
                    impact="medium",
                    confidence=0.9,
                    claim_type="inference",
                    observation="The quest exposed a lower-value line.",
                    recommendation="Consider the alternate sequence first.",
                    evidence_action_ids=(self.action_id,),
                    evidence_turns=(2,),
                ),
            ),
            usage={"input_tokens": 100, "output_tokens": 40},
        )


def service(repo):
    ids = iter([RUN, FINDING, REPORT, UUID("00000000-0000-0000-0000-000000000809")])
    return CoachService(
        repository=repo,
        read_connection_factory=connection,
        transaction_factory=connection,
        clock=lambda: NOW,
        uuid_factory=lambda: next(ids),
    )


def test_coach_uses_effective_actions_and_catalog_facts_then_caches_result():
    repo = FakeRepository()
    analyzer = FakeAnalyzer()
    svc = service(repo)

    result = svc.analyze(
        member_id=MEMBER,
        normalization_id=NORMALIZATION,
        feature_set_id=FEATURES,
        catalog_snapshot_id=CATALOG,
        analyzer=analyzer,
    )

    assert result.cached is False
    assert result.finding_count == 1
    assert "sequencing" in result.content
    assert analyzer.calls == 1
    assert [a["seq"] for a in analyzer.last_evidence["normalization"]["effective_actions"]] == [1, 4]
    assert "actions" not in analyzer.last_evidence["normalization"]
    assert analyzer.last_evidence["catalog"]["facts"]["12-11"]["ink_colors"] == ["sapphire"]

    cached = svc.analyze(
        member_id=MEMBER,
        normalization_id=NORMALIZATION,
        feature_set_id=FEATURES,
        catalog_snapshot_id=CATALOG,
        analyzer=analyzer,
    )
    assert cached.cached is True
    assert cached.finding_count == 1
    assert cached.analysis_run_id == result.analysis_run_id
    assert analyzer.calls == 1


def test_coach_rejects_citation_to_undone_or_non_effective_action_and_marks_run_failed():
    repo = FakeRepository()
    analyzer = FakeAnalyzer(action_id=3)
    svc = service(repo)

    with pytest.raises(CoachError, match="not in effective replay evidence"):
        svc.analyze(
            member_id=MEMBER,
            normalization_id=NORMALIZATION,
            feature_set_id=FEATURES,
            catalog_snapshot_id=CATALOG,
            analyzer=analyzer,
        )
    assert repo.failed is not None
    assert repo.runs[RUN]["status"] == "failed"
    assert RUN not in repo.reports


def test_coach_enforces_member_access_before_analyzer_runs():
    repo = FakeRepository()
    analyzer = FakeAnalyzer()
    svc = service(repo)
    other = UUID("00000000-0000-0000-0000-000000000899")

    with pytest.raises(CoachAccessError, match="not available"):
        svc.analyze(
            member_id=other,
            normalization_id=NORMALIZATION,
            feature_set_id=FEATURES,
            catalog_snapshot_id=CATALOG,
            analyzer=analyzer,
        )
    assert analyzer.calls == 0


def test_validation_requires_cited_evidence_and_valid_turns():
    evidence = {
        "normalization": {
            "effective_actions": [{"seq": 10, "gameplay_turn": 5}],
        }
    }
    no_evidence = CoachAnalyzerResult(
        summary="x",
        findings=(CoachFindingDraft("x", "low", 0.5, "fact", "o", "r"),),
    )
    with pytest.raises(CoachError, match="must cite"):
        CoachService._validate_analyzer_result(no_evidence, evidence)

    bad_turn = CoachAnalyzerResult(
        summary="x",
        findings=(CoachFindingDraft("x", "low", 0.5, "fact", "o", "r", evidence_turns=(99,)),),
    )
    with pytest.raises(CoachError, match="turn that is not"):
        CoachService._validate_analyzer_result(bad_turn, evidence)


def test_retry_can_recover_a_run_left_running_by_a_crashed_worker():
    repo = FakeRepository()
    analyzer = FakeAnalyzer()
    svc = service(repo)
    # Simulate the first worker having created the durable run and then dying
    # before it could call the analyzer or mark the run failed.
    evidence = svc._evidence_package(
        member_id=MEMBER,
        normalization_id=NORMALIZATION,
        feature_set_id=FEATURES,
        catalog_snapshot_id=CATALOG,
        decklist_id=None,
    )
    from lorcana.coach.service import canonical_sha256
    analyzer_input = {**evidence, "analysis_config": {}}
    input_sha = canonical_sha256(analyzer_input)
    key = canonical_sha256({
        "member_id": str(MEMBER),
        "normalization_id": str(NORMALIZATION),
        "feature_set_id": str(FEATURES),
        "catalog_snapshot_id": str(CATALOG),
        "decklist_id": None,
        "analyzer_provider": analyzer.provider,
        "analyzer_model": analyzer.model,
        "prompt_version": analyzer.prompt_version,
        "analysis_config": {},
        "input_sha256": input_sha,
    })
    repo.runs[RUN] = {
        "analysis_run_id": RUN,
        "idempotency_key": key,
        "status": "running",
    }

    with pytest.raises(Exception, match="already running"):
        svc.analyze(
            member_id=MEMBER, normalization_id=NORMALIZATION, feature_set_id=FEATURES,
            catalog_snapshot_id=CATALOG, analyzer=analyzer,
        )
    recovered = svc.analyze(
        member_id=MEMBER, normalization_id=NORMALIZATION, feature_set_id=FEATURES,
        catalog_snapshot_id=CATALOG, analyzer=analyzer, restart_running=True,
    )
    assert recovered.analysis_run_id == RUN
    assert repo.runs[RUN]["status"] == "succeeded"
    assert analyzer.calls == 1

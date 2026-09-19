from dataclasses import replace
import json
from pathlib import Path
import pytest
from lorcana.coach.grounding import validate_finding_grounding
from lorcana.coach.rules import digest, for_game, load_bundle
from lorcana.coach.types import CoachFindingDraft


def evidence():
    return {"rules": {"citations": {"CR:2.2.0:p3": {"text": "fixture"}}},
            "catalog": {"facts": {"3-223": {"canonical_card_id": "3-16"}}}}


def finding(**kwargs):
    return CoachFindingDraft("challenge", "high", .8, "inference", "Observation", "Recommendation",
        evidence_action_ids=(2,), payload={"claim_basis": "rules_interpretation",
        "rule_citations": ["CR:2.2.0:p3"], "card_citations": ["3-223"]}, **kwargs)


def test_rules_claim_must_remain_an_interpretation():
    validate_finding_grounding(finding(), evidence())
    with pytest.raises(ValueError, match="verified facts"):
        validate_finding_grounding(replace(finding(), claim_type="fact"), evidence())


@pytest.mark.parametrize("key,value", [("rule_citations", ["CR:made-up:p1"]),
    ("card_citations", ["3-16"]), ("rule_citations", []), ("card_citations", []),
    ("rule_citations", "CR:2.2.0:p3"), ("claim_basis", "verified_legality")])
def test_missing_fabricated_or_malformed_references_are_rejected(key, value):
    f = finding()
    f.payload[key] = value
    with pytest.raises(ValueError):
        validate_finding_grounding(f, evidence())


def bundle():
    data = {"effective_from": "2026-07-09", "verified_through": "2026-09-19",
            "source_url": "https://files.disneylorcana.com/test.pdf",
            "citations": {"CR:test:p1": {"text": "fixture"}}}
    return {**data, "bundle_sha256": digest(data)}


@pytest.mark.parametrize("day,coverage", [("2026-05-10", "before_reference"),
    ("2026-07-09", "within_reference_window"), ("2026-09-19", "within_reference_window"),
    ("2026-09-20", "after_review"), (None, "game_date_unknown")])
def test_games_remain_reviewable_without_claiming_historical_legality(day, coverage):
    rules = for_game(bundle(), day)
    assert rules["status"] == "available"
    assert rules["date_coverage"] == coverage
    assert rules["review_mode"] == "current_reference"
    assert rules["historical_legality_verified"] is False
    assert rules["citations"] == bundle()["citations"]
    assert "not a historical legality verdict" in rules["review_notice"]


def test_bundle_integrity_and_official_source(tmp_path):
    path = tmp_path / "rules.json"
    data = bundle()
    path.write_text(json.dumps(data))
    assert load_bundle(path) == data
    data["citations"]["CR:test:p1"]["text"] = "tampered"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="checksum"):
        load_bundle(path)
    data = bundle()
    data.pop("bundle_sha256")
    data["source_url"] = "https://files.disneylorcana.com.evil.test/rules.pdf"
    data["bundle_sha256"] = digest(data)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="official"):
        load_bundle(path)


def test_missing_stats_or_ink_colors_are_explicitly_incomplete():
    from lorcana.coach.grounding import incomplete_card_ids
    card = {"card_type": "Character", "ink_colors": ["amber"], "cost": 2,
            "inkable": True, "strength": 0, "willpower": 2, "lore": 1}
    assert incomplete_card_ids({"3-16": card}) == []
    assert incomplete_card_ids({"3-16": {**card, "ink_colors": []}}) == ["3-16"]
    assert incomplete_card_ids({"3-16": {**card, "willpower": None}}) == ["3-16"]


def test_packaged_references_load_without_configuration_from_any_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rules = load_bundle()
    assert len(rules["documents"]) >= 7
    assert len(rules["citations"]) >= 182
    assert {d["kind"] for d in rules["documents"].values()} == {"comprehensive_rules", "set_release_notes", "tournament_rules"}
    assert all(c["document_id"] in rules["documents"] for c in rules["citations"].values())


def test_explicit_missing_path_does_not_silently_fall_back(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_bundle(str(tmp_path / "missing.json"))


def test_report_links_to_set_guide_and_discloses_scope_even_without_findings():
    from lorcana.coach.service import _render_report
    rules = for_game(load_bundle(), "2026-05-10")
    f = finding()
    f.payload["rule_citations"] = ["SET:fabled:p1"]
    report = _render_report("Summary", (f,), rules)
    assert "Fabled_SetReleaseNotes_EN.pdf#page=1" in report
    assert "Comprehensive-Rules_2.2.0-EN.pdf#page=1" not in report
    assert "predates" in report
    assert rules["review_notice"] in _render_report("Summary", (), rules)


def test_unknown_document_citation_is_rejected(tmp_path):
    data = load_bundle()
    data.pop("bundle_sha256")
    data["citations"][next(iter(data["citations"]))]["document_id"] = "missing"
    data["bundle_sha256"] = digest(data)
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unknown document"):
        load_bundle(path)

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


@pytest.mark.parametrize("day,status", [("2026-07-08", "outside_verified_dates"),
    ("2026-07-09", "available"), ("2026-09-19", "available"),
    ("2026-09-20", "outside_verified_dates"), (None, "game_date_unknown")])
def test_historical_games_never_silently_use_wrong_rules(day, status):
    assert for_game(bundle(), day)["status"] == status


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

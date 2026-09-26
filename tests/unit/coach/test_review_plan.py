from dataclasses import replace
import pytest
from lorcana.coach.review_plan import prepare_review, request_budget, duration_facts, validate_generated_advice, ReviewBlocked
from lorcana.coach.types import CoachAnalyzerResult, CoachFindingDraft


ALICE = {"name": "Alice - Savvy Sailor", "rules_text": "Ward. AHOY! Whenever this character quests, another chosen character of yours gets +1 Lore and gains Ward until the start of your next turn."}


def evidence():
    return {"normalization": {"effective_actions": [
        {"seq": 1, "gameplay_turn": 4, "actor_is_perspective": True, "type": "quest", "card_id": "9-1", "context": {"my": {"hand": [{"id": "9-1"}]}}},
        {"seq": 2, "gameplay_turn": 6, "actor_is_perspective": True, "type": "play", "card_id": "9-1"}]},
        "catalog": {"facts": {"9-1": ALICE}},
        "rules": {"status": "available", "citations": {"CR:1": {"text": "Whenever a character quests; until start of next turn.", "page": 1}}},
        "analysis_config": {"large_duplicate_grounding": "x" * 200000}, "features": {"irrelevant": "x" * 200000}}


def result(text, claim="inference"):
    return CoachAnalyzerResult(summary="Review", findings=(CoachFindingDraft(
        "sequencing", "high", .98, claim, text, "Review this decision", evidence_action_ids=(1,),
        payload={"claim_basis":"strategic_inference", "rule_citations": [], "card_citations":["9-1"]}),))


def test_selection_preserves_whole_turn_and_context_without_duplicate_payloads():
    e=evidence(); p=prepare_review(e, [4])
    assert p["normalization"]["effective_actions"] == e["normalization"]["effective_actions"][:1]
    assert "analysis_config" not in p and "features" not in p
    assert p["catalog"]["facts"]["9-1"]["rules_text"] == ALICE["rules_text"]
    assert p["recorded_statistics"] == {"play":1, "quest":1}
    assert p["rules"]["retrieval_complete"] is False


def test_alice_expiry_is_explicit_and_known_bad_advice_is_rejected():
    p=prepare_review(evidence(), [4])
    assert p["duration_facts"][0]["applies_during_next_turn_quest"] is False
    with pytest.raises(ReviewBlocked, match="expiring effect"):
        validate_generated_advice(result("Used AHOY! to increase Robin Hood's lore for the next turn."), p)
    # This guard deliberately abstains even on possibly correct next-turn lore prose.
    validate_generated_advice(result("Alice quested in the recorded turn."), p)


def test_fact_label_cannot_bypass_by_claiming_replay_observation():
    p=prepare_review(evidence(), [4]); r=result("Great sequencing", "fact")
    r.findings[0].payload["claim_basis"]="replay_observation"
    with pytest.raises(ReviewBlocked, match="fact"):
        validate_generated_advice(r,p)


def test_citations_outside_selected_turn_are_rejected():
    p=prepare_review(evidence(), [4]); r=result("Observation")
    r=replace(r, findings=(replace(r.findings[0], evidence_action_ids=(2,)),))
    with pytest.raises(ReviewBlocked, match="outside"):
        validate_generated_advice(r,p)


def test_large_request_and_unknown_model_fail_closed():
    b=request_budget({"model":"gpt-5.4", "input":"x"*154332*4, "max_output_tokens":1200})
    assert not b["allowed"]
    with pytest.raises(ReviewBlocked, match="pricing"):
        request_budget({"model":"unknown", "input":"hi", "max_output_tokens":1200})


def test_no_rules_match_does_not_send_full_bundle_as_fallback():
    e=evidence();e["rules"]["citations"]={"unrelated":{"text":"Unrelated content"}}
    with pytest.raises(ReviewBlocked, match="No relevant"):
        prepare_review(e,[4])

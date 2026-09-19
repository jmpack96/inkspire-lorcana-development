"""Structural evidence checks, deliberately not a claim of semantic verification."""
from lorcana.coach.types import CoachFindingDraft


def validate_finding_grounding(finding: CoachFindingDraft, evidence: dict) -> None:
    basis = finding.payload.get("claim_basis")
    if basis not in {"replay_observation", "strategic_inference", "rules_interpretation"}:
        raise ValueError("Finding must declare its claim basis")
    if basis != "replay_observation" and finding.claim_type != "inference":
        raise ValueError("Strategy and rules interpretations cannot be presented as verified facts")
    rules = finding.payload.get("rule_citations")
    cards = finding.payload.get("card_citations")
    for refs, allowed, kind in (
        (rules, evidence.get("rules", {}).get("citations", {}), "rule"),
        (cards, evidence.get("catalog", {}).get("facts", {}), "card"),
    ):
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError(f"Finding {kind} citations must be string lists")
        if any(ref not in allowed for ref in refs):
            raise ValueError(f"Finding cites an unavailable {kind} reference")
    if basis == "rules_interpretation" and (not rules or not cards):
        raise ValueError("Rules interpretation requires official rules and card citations")


def incomplete_card_ids(facts: dict) -> list[str]:
    missing = []
    for card_id, card in facts.items():
        card_type = (card.get("card_type") or "").casefold()
        required = ["cost", "inkable", "card_type"]
        if card_type == "character":
            required += ["strength", "willpower", "lore"]
        elif card_type == "location":
            required += ["willpower", "lore", "move_cost"]
        if not card.get("ink_colors") or any(card.get(key) is None for key in required):
            missing.append(card_id)
    return sorted(missing)

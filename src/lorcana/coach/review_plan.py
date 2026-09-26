"""Offline decision selection and conservative request cost bounds.

Selection is a review aid, not a claim that a turn contains a mistake. Whole
selected turns and complete rule pages are retained; oversize input is blocked.
"""
from collections import Counter
import json
import re

VERSION = "bounded-review-v1"
MAX_COST_USD = 0.05
MAX_OUTPUT_TOKENS = 1200
# Standard rates checked 2026-09-19. Unknown models fail closed.
RATES = {"gpt-5.4": (2.50, 15.0), "gpt-5.4-2026-03-05": (2.50, 15.0)}


class ReviewBlocked(ValueError):
    pass


def card_ids(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"id", "card_id", "target_card_id"} and isinstance(child, str) and re.fullmatch(r"\d+-\d+", child):
                found.add(child)
            found.update(card_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(card_ids(child))
    return found


def duration_facts(facts):
    result = []
    for key, card in facts.items():
        text = card.get("rules_text") or ""
        if "until the start of your next turn" in text.casefold():
            result.append({"card_id": key, "name": card.get("name"),
                "source_text": text, "expires": "start_of_controller_next_turn",
                "applies_during_next_turn_quest": False,
                "scope": "Only the effect qualified by this exact duration; not every ability on the card."})
    return result


def prepare_review(evidence, turns=None):
    actions = evidence["normalization"]["effective_actions"]
    counts = Counter(a.get("type", "unknown") for a in actions if a.get("actor_is_perspective") is True)
    available = sorted({a["gameplay_turn"] for a in actions
        if isinstance(a.get("gameplay_turn"), int) and a.get("actor_is_perspective") is True})
    selected = list(dict.fromkeys(turns)) if turns else available[:1]
    if not selected or len(selected) > 2 or any(t not in available for t in selected):
        raise ReviewBlocked("Select one or two recorded player turns with --turn; no valid selection available")
    picked = [a for a in actions if a.get("gameplay_turn") in selected]
    ids = card_ids(picked)
    all_facts = evidence["catalog"]["facts"]
    missing = sorted(ids - set(all_facts))
    if missing:
        raise ReviewBlocked("Selected decision has unresolved cards: " + ", ".join(missing))
    facts = {key: all_facts[key] for key in sorted(ids)}
    # Keep full card text and board/hand context. Retrieve complete paragraphs/pages,
    # not isolated keyword definitions; absence is not proof that no exception exists.
    terms = set()
    for card in facts.values():
        terms.update(re.findall(r"[a-z]{5,}", (card.get("rules_text") or "").lower()))
    terms -= {"character", "chosen", "another", "disney", "lorcana", "their", "there", "cards", "yours", "other"}
    pages = evidence.get("rules", {}).get("citations", {})
    ranked = []
    for key, page in pages.items():
        text = page["text"].lower()
        words = set(re.findall(r"[a-z]{5,}", text))
        score = len(terms & words)
        score += 20 * sum(bool(c.get("name")) and c["name"].lower() in text for c in facts.values())
        if score:
            ranked.append((-score, key))
    selected_refs = {key: pages[key] for _, key in sorted(ranked)[:2]}
    if not selected_refs:
        raise ReviewBlocked("No relevant rule pages retrieved; refine the decision or references before analysis")
    rules = {k:v for k,v in evidence["rules"].items() if k not in {"citations", "documents"}}
    used_docs = {c.get("document_id") for c in selected_refs.values()}
    rules["documents"] = {k:v for k,v in evidence["rules"].get("documents", {}).items() if k in used_docs}
    rules["citations"] = selected_refs
    rules["retrieval_complete"] = False
    return {"game_id": evidence.get("game_id"), "played_at": evidence.get("played_at"),
        "review_scope": {"version": VERSION, "selected_turns": selected,
            "selection": "Explicit selection" if turns else "First recorded player turn; not ranked by strategic importance",
            "limitation": "Partial game review. Rules retrieval may omit exceptions. Do not infer omitted history, state timing, or hidden information."},
        "recorded_statistics": dict(sorted(counts.items())),
        "duration_facts": duration_facts(facts),
        "normalization": {"effective_actions": picked},
        "catalog": {"facts": facts, "missing_card_ids": []}, "rules": rules}


def request_budget(body, max_cost=MAX_COST_USD):
    if body["model"] not in RATES:
        raise ReviewBlocked("Model has no reviewed pricing; use gpt-5.4 or add verified pricing before analysis")
    # UTF-8 bytes upper-bound text tokens for byte-level tokenization. Count all
    # serialized request fields, plus a conservative framing allowance. No caching
    # discount is assumed. This is deliberately much stricter than chars/4.
    token_bound = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()) + 1024
    input_rate, output_rate = RATES[body["model"]]
    upper_cost = (token_bound * input_rate + body["max_output_tokens"] * output_rate) / 1_000_000
    return {"input_token_upper_bound": token_bound, "max_output_tokens": body["max_output_tokens"],
        "estimated_upper_cost_usd": round(upper_cost, 6), "limit_usd": max_cost,
        "allowed": upper_cost <= max_cost and token_bound <= 272000,
        "pricing_basis": "2026-09-19 standard USD rates, no cache discount; not a provider billing guarantee"}


def validate_generated_advice(result, evidence):
    if any(f.claim_type != "inference" for f in result.findings):
        raise ReviewBlocked("Generated advice cannot be labeled fact")
    valid_ids = {a.get("seq") for a in evidence["normalization"]["effective_actions"]}
    valid_turns = {a.get("gameplay_turn") for a in evidence["normalization"]["effective_actions"]}
    for finding in result.findings:
        if not finding.evidence_action_ids and not finding.evidence_turns:
            raise ReviewBlocked("Advice must cite a selected action or turn")
        if set(finding.evidence_action_ids) - valid_ids or set(finding.evidence_turns) - valid_turns:
            raise ReviewBlocked("Advice cites evidence outside the selected decisions")
    # Narrow abstention guard: don't try to prove the semantics of arbitrary prose.
    # If next-turn lore advice involves an expiring effect, suppress the report for
    # human review even if the wording could be correct. This catches the known
    # Alice failure; it is not a general rules engine.
    text = " ".join([result.summary] + [f.observation + " " + f.recommendation for f in result.findings]).lower()
    if evidence.get("duration_facts") and "next turn" in text and "lore" in text:
        raise ReviewBlocked("Next-turn lore advice involves an expiring effect; human review required")

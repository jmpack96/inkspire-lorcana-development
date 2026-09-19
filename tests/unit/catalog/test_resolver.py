from copy import deepcopy
import pytest
from lorcana.catalog.resolver import collect_names, resolve_printings


def piglet(card_id="3-16", **kwargs):
    return {"card_id": card_id, "name": "Piglet - Pooh Pirate Captain", "collector_number": "16",
            "ink_colors": ["amber"], "cost": 2, "inkable": True, "card_type": "Character",
            "classifications": ["Dreamborn"], "rules_text": "fixture text",
            "raw": {"source_raw": {"strength": 2, "willpower": 2, "lore": 1}}, **kwargs}


def test_reviewed_printing_preserves_source_id_and_records_target():
    replay = [{"card_id": "3-223", "card_name": "Piglet – Pooh Pirate Captain"}]
    before = deepcopy(replay)
    resolved, decisions = resolve_printings(["3-223"], collect_names(replay), [piglet()])
    assert resolved["3-223"]["card_id"] == "3-16"
    assert decisions["3-223"]["status"] == "reviewed_alias"
    assert replay == before


def test_unknown_printing_only_suggests_candidate_even_with_same_full_name():
    resolved, decisions = resolve_printings(["3-999"], collect_names([
        {"id": "3-999", "name": "Piglet - Pooh Pirate Captain"}]), [piglet()])
    assert not resolved
    assert decisions["3-999"] == {"status": "unresolved", "candidate_ids": ["3-16"]}


@pytest.mark.parametrize("name", ["Piglet", "Piglet - Brave Friend", ""])
def test_alias_cannot_override_different_or_incomplete_replay_identity(name):
    resolved, _ = resolve_printings(["3-223"], collect_names([{"id": "3-223", "name": name}]), [piglet()])
    assert not resolved


def test_conflicting_printing_rules_block_resolution():
    resolved, decisions = resolve_printings(["3-223"], collect_names([
        {"id": "3-223", "name": piglet()["name"]}]), [piglet(), piglet("9-16", rules_text="different")])
    assert not resolved
    assert decisions["3-223"]["status"] == "ambiguous_gameplay_data"


def test_exact_id_with_wrong_name_is_blocked():
    resolved, decisions = resolve_printings(["3-16"], collect_names([
        {"id": "3-16", "name": "Piglet - Wrong Subtitle"}]), [piglet()])
    assert not resolved
    assert decisions["3-16"]["status"] == "identity_conflict"


def test_equivalent_reprints_resolve_deterministically():
    cards = [piglet("9-216", collector_number="216"), piglet()]
    names = collect_names([{"id": "3-223", "name": piglet()["name"]}])
    assert resolve_printings(["3-223"], names, cards) == resolve_printings(["3-223"], names, cards[::-1])
    assert resolve_printings(["3-223"], names, cards)[0]["3-223"]["card_id"] == "3-16"

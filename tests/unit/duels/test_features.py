import gzip
import json
from pathlib import Path

from lorcana.duels.features import FEATURE_EXTRACTOR_VERSION, extract_features

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "duels"


def test_feature_extractor_is_deterministic_and_undo_adjusted():
    path = FIXTURES / "01a09c43-d14f-79d0-baa0-f98904afbdae.normalized.json.gz"
    normalized = json.loads(gzip.decompress(path.read_bytes()))
    first = extract_features(normalized)
    second = extract_features(normalized)
    assert first == second
    assert first["extractor_version"] == FEATURE_EXTRACTOR_VERSION
    assert first["game"]["game_id"] == normalized["game"]["game_id"]
    assert sum(first["action_counts"].values()) == len(normalized["effective_actions"])
    assert len(first["undo_ranges"]) == len(normalized["undo_ranges"])
    assert "2" in first["perspective_turns"]


def test_features_only_count_effective_actions():
    path = FIXTURES / "01a09c43-d14f-79d0-baa0-f98904afbdae.normalized.json.gz"
    normalized = json.loads(gzip.decompress(path.read_bytes()))
    features = extract_features(normalized)
    assert sum(features["action_counts"].values()) == len(normalized["effective_actions"])
    assert len(normalized["actions"]) >= len(normalized["effective_actions"])

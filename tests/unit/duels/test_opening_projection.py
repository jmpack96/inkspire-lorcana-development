import gzip
import json
from pathlib import Path

import pytest

from lorcana.duels.opening_projection import compact_opening, projection_values, validated_mulligan
from lorcana.duels.practice import opening_metrics, RAMP_CARDS
from lorcana.duels.replay_parser import parse_replay

FIXTURES = Path(__file__).resolve().parents[2] / 'fixtures' / 'duels'


@pytest.mark.parametrize('path', sorted(FIXTURES.glob('*.replay.gz')))
def test_compact_evidence_preserves_metrics_and_omits_boards(path):
    normalized = parse_replay(json.loads(gzip.decompress(path.read_bytes())))
    compact = compact_opening(normalized)
    for targets in ((), RAMP_CARDS, ('not a real card',), ('1-1', 'Tipo - Growing Son')):
        assert opening_metrics(compact, targets) == opening_metrics(normalized, targets)
    assert validated_mulligan(compact) == validated_mulligan(normalized)
    assert len(json.dumps(compact)) < len(json.dumps(normalized)) / 2
    assert all('opponent' not in a['coach_context'] for a in compact['effective_actions'])
    assert all(set(a['coach_context']['my']) <= {'hand', 'ink_count', 'ready_ink'}
               for a in compact['effective_actions'])
    values = projection_values(normalized)
    assert values['decklist'] == normalized.get('decklist')
    assert values['mulligan_count'] == validated_mulligan(normalized)


@pytest.mark.parametrize('change', [
    {'parser_warnings': ['warning']}, {'starting_hand': []},
    {'game': {'perspective': None}}, {'mulligan': {'count': True}},
])
def test_compaction_keeps_invalid_evidence_invalid(change):
    path = next(FIXTURES.glob('*.replay.gz'))
    normalized = parse_replay(json.loads(gzip.decompress(path.read_bytes())))
    normalized.update(change)
    assert validated_mulligan(compact_opening(normalized)) is None
    assert opening_metrics(compact_opening(normalized), RAMP_CARDS) == opening_metrics(normalized, RAMP_CARDS)

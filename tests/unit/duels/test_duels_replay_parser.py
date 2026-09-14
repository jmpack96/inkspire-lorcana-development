import copy
import gzip
import json
import unittest
from pathlib import Path

from lorcana.duels.replay_parser import parse_replay


FIXTURES = Path(__file__).parents[2] / "fixtures" / "duels"


class ReplayRegressionTests(unittest.TestCase):
    def test_saved_replays(self):
        fixtures = sorted(FIXTURES.glob("*.replay.gz"))
        self.assertEqual(len(fixtures), 2)
        total_challenges = 0
        for fixture in fixtures:
            with self.subTest(replay=fixture.name):
                raw = json.loads(gzip.decompress(fixture.read_bytes()))
                untouched = copy.deepcopy(raw)
                expected_path = fixture.with_name(fixture.name.replace(".replay.gz", ".normalized.json.gz"))
                expected = json.loads(gzip.decompress(expected_path.read_bytes()))
                result = parse_replay(raw)
                self.assertEqual(result, expected)
                self.assertEqual(raw, untouched)
                self.assertEqual(result["parser_warnings"], [])
                self.assertTrue(result["undo_ranges"])
                self.assertTrue(any(action["undone"] for action in result["actions"]))
                self.assertTrue(all(not action["undone"] for action in result["effective_actions"]))
                for action in result["actions"]:
                    if action["raw_type"] == "ATTACK":
                        total_challenges += 1
                        self.assertEqual(action["type"], "challenge")
                        self.assertEqual(action["raw_taken_action"]["type"], "CHALLENGE")
                        self.assertIsNotNone(action["challenge"]["combat_math"])
        self.assertEqual(total_challenges, 4)

    def test_rejects_unknown_replay_format(self):
        with self.assertRaisesRegex(ValueError, "Unsupported replay format"):
            parse_replay({"format": "unknown"})

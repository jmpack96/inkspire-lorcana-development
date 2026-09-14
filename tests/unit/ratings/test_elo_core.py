import contextlib
import io
import unittest
from lorcana.ratings.elo import EloCalculator
from lorcana.ratings.types import RatingMatch
from oracles.legacy_elo import calculate_reference


def match(match_id=1, p1=1, p2=2, winner=1, draw=False):
    return RatingMatch(match_id, 10, 20, p1, p2, winner, draw, "2026-01-01T00:00:00Z", 0, 1)


class EloCoreTests(unittest.TestCase):
    def test_equal_players_win_then_draw(self):
        calc = EloCalculator()
        history = calc.process(match())
        self.assertEqual([r.rating_after for r in history], [1516.0, 1484.0])
        self.assertEqual([r.result for r in history], ["WIN", "LOSS"])
        self.assertEqual(calc.players[2].peak, 1500.0)
        calc.process(match(2, winner=None, draw=True))
        self.assertLess(calc.players[1].rating, 1516.0)
        self.assertAlmostEqual(sum(p.rating for p in calc.players.values()), 3000.0)
        self.assertEqual(calc.players[1].draws, 1)

    def test_invalid_inputs_do_not_create_players(self):
        calc = EloCalculator()
        for m in (match(winner=3), match(winner=None), match(p2=1)):
            self.assertEqual(calc.process(m), ())
        self.assertEqual(calc.players, {})
        self.assertEqual(calc.invalid_matches, 3)

    def test_chronological_sequence_matches_frozen_legacy_loop(self):
        matches = [match(), match(2, p1=2, p2=3, winner=3), match(3, p1=1, p2=3, winner=None, draw=True), match(4, winner=99)]
        with contextlib.redirect_stdout(io.StringIO()):
            expected = calculate_reference([tuple(m.__dict__.values()) for m in matches])
        calc = EloCalculator()
        actual_history = [row for m in matches for row in calc.process(m)]
        self.assertEqual(actual_history, expected[3])
        self.assertEqual(calc.matches_processed, expected[4])
        self.assertEqual(calc.invalid_matches, expected[5])
        for player, state in calc.players.items():
            self.assertEqual(state.rating, expected[0][player])
            self.assertEqual(state.peak, expected[1][player])
            self.assertEqual(state.matches, expected[2][player]["matches"])

    def test_empty_and_invalid_parameters(self):
        self.assertEqual(EloCalculator().matches_processed, 0)
        for k in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                EloCalculator(k_factor=k)

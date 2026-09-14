"""Pure Elo arithmetic. Callers supply eligible matches in chronological order."""
import math
from typing import Dict, Tuple

from lorcana.ratings.types import HistoryRow, PlayerRating, RatingMatch

STARTING_RATING = 1500.0
K_FACTOR = 32.0
ALGORITHM = "elo_v2_2player_only"


def expected_score(rating_a, rating_b):
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))


def updated_rating(rating, opponent_rating, actual_score, k_factor=K_FACTOR):
    return rating + k_factor * (actual_score - expected_score(rating, opponent_rating))


class EloCalculator:
    """Incremental calculator; retains only player state, not match history.

    Filtering and ordering are the caller's responsibility. Invalid results
    return no history and cannot add phantom players. Each accepted match
    returns two history rows in source player order.
    """

    def __init__(self, starting_rating=STARTING_RATING, k_factor=K_FACTOR):
        if not math.isfinite(starting_rating) or not math.isfinite(k_factor) or k_factor <= 0:
            raise ValueError("Ratings must be finite and k_factor must be positive")
        self.starting_rating = starting_rating
        self.k_factor = k_factor
        self.players: Dict[int, PlayerRating] = {}
        self.matches_processed = 0
        self.invalid_matches = 0

    def process(self, match: RatingMatch) -> Tuple[HistoryRow, ...]:
        p1, p2 = match.player1_id, match.player2_id
        if (p1 is None or p2 is None or p1 == p2
                or (match.winner_id is not None and match.winner_id not in (p1, p2))
                or (match.winner_id is None and not match.is_draw)):
            self.invalid_matches += 1
            return ()
        # Preserve legacy precedence for draws. Contradictory draw/winner
        # policy is deliberately not changed in this parity extraction.
        if match.is_draw:
            scores, labels = (0.5, 0.5), ("DRAW", "DRAW")
        elif match.winner_id == p1:
            scores, labels = (1.0, 0.0), ("WIN", "LOSS")
        else:
            scores, labels = (0.0, 1.0), ("LOSS", "WIN")
        initial = PlayerRating(rating=self.starting_rating, peak=self.starting_rating)
        before = (self.players.get(p1, initial), self.players.get(p2, initial))
        history = []
        for index, player in enumerate((p1, p2)):
            old, opponent = before[index], before[1-index]
            rating = updated_rating(old.rating, opponent.rating, scores[index], self.k_factor)
            label = labels[index]
            self.players[player] = PlayerRating(
                rating=rating, matches=old.matches + 1,
                wins=old.wins + (label == "WIN"), losses=old.losses + (label == "LOSS"),
                draws=old.draws + (label == "DRAW"), peak=max(old.peak, rating),
            )
            history.append(HistoryRow(player, match.match_id, match.event_id,
                                      old.rating, rating, rating-old.rating,
                                      (p1, p2)[1-index], opponent.rating, label))
        self.matches_processed += 1
        return tuple(history)

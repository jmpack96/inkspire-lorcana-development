"""Frozen arithmetic oracle from commit 8f03946 calculate_elo.py.

Only the loop's enclosing function and return were added; original algorithm
body is retained. Do not update this oracle when changing the new calculator.
It neither opens a database nor imports production code.
"""
import math
from collections import defaultdict
STARTING_RATING = 1500.0
K_FACTOR = 32.0

def expected_score(rating_a, rating_b):
    return 1.0 / (
        1.0
        + math.pow(
            10.0,
            (rating_b - rating_a) / 400.0,
        )
    )

def updated_rating(
    rating,
    opponent_rating,
    actual_score,
):
    expected = expected_score(
        rating,
        opponent_rating,
    )

    return (
        rating
        + K_FACTOR
        * (actual_score - expected)
    )

def calculate_reference(matches):
    ratings = defaultdict(
        lambda: STARTING_RATING
    )

    peak_ratings = defaultdict(
        lambda: STARTING_RATING
    )

    records = defaultdict(
        lambda: {
            "matches": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
        }
    )

    history_rows = []

    processed_matches = 0
    invalid_matches = 0

    for row in matches:
        (
            match_id,
            event_id,
            round_id,
            player1_id,
            player2_id,
            winner_id,
            is_draw,
            start_datetime,
            phase_order,
            round_number,
        ) = row

        # Defensive validation even though the SQL
        # should already leave us with valid matches.
        if (
            winner_id is not None
            and winner_id not in (
                player1_id,
                player2_id,
            )
        ):
            invalid_matches += 1

            print(
                f"WARNING: skipping match {match_id}: "
                f"winner {winner_id} is not "
                f"player1 {player1_id} or "
                f"player2 {player2_id}"
            )

            continue

        rating1_before = ratings[player1_id]
        rating2_before = ratings[player2_id]

        if is_draw:
            result1 = 0.5
            result2 = 0.5

            result1_label = "DRAW"
            result2_label = "DRAW"

            records[player1_id]["draws"] += 1
            records[player2_id]["draws"] += 1

        elif winner_id == player1_id:
            result1 = 1.0
            result2 = 0.0

            result1_label = "WIN"
            result2_label = "LOSS"

            records[player1_id]["wins"] += 1
            records[player2_id]["losses"] += 1

        elif winner_id == player2_id:
            result1 = 0.0
            result2 = 1.0

            result1_label = "LOSS"
            result2_label = "WIN"

            records[player1_id]["losses"] += 1
            records[player2_id]["wins"] += 1

        else:
            invalid_matches += 1

            print(
                f"WARNING: skipping match {match_id}: "
                f"could not determine result"
            )

            continue

        rating1_after = updated_rating(
            rating1_before,
            rating2_before,
            result1,
        )

        rating2_after = updated_rating(
            rating2_before,
            rating1_before,
            result2,
        )

        ratings[player1_id] = rating1_after
        ratings[player2_id] = rating2_after

        peak_ratings[player1_id] = max(
            peak_ratings[player1_id],
            rating1_after,
        )

        peak_ratings[player2_id] = max(
            peak_ratings[player2_id],
            rating2_after,
        )

        records[player1_id]["matches"] += 1
        records[player2_id]["matches"] += 1

        history_rows.append(
            (
                player1_id,
                match_id,
                event_id,
                rating1_before,
                rating1_after,
                rating1_after - rating1_before,
                player2_id,
                rating2_before,
                result1_label,
            )
        )

        history_rows.append(
            (
                player2_id,
                match_id,
                event_id,
                rating2_before,
                rating2_after,
                rating2_after - rating2_before,
                player1_id,
                rating1_before,
                result2_label,
            )
        )

        processed_matches += 1

    return ratings, peak_ratings, records, history_rows, processed_matches, invalid_matches

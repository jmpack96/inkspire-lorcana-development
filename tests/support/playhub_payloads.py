from __future__ import annotations


def raw_event(*, rounds=1, generated=True):
    raw_rounds = []
    for index in range(rounds):
        raw_rounds.append({
            "id": 101 + index,
            "round_number": index + 1,
            "round_type": "PLAY_VS_OPPONENT",
            "status": "COMPLETE",
            "pairings_status": "GENERATED" if generated else "PENDING",
            "standings_status": "GENERATED" if generated else "PENDING",
            "final_round_in_event": index == rounds - 1,
        })
    return {
        "id": 1,
        "name": "Test Event",
        "start_datetime": "2026-09-13T18:00:00Z",
        "end_datetime": "2026-09-13T22:00:00Z",
        "gameplay_format": {"id": "core", "name": "Core"},
        "event_type": "SET_CHAMP",
        "store": {"id": "s1", "name": "Store"},
        "tournament_phases": [{
            "id": 10,
            "phase_name": "Swiss",
            "order_in_phases": 1,
            "round_type": "SWISS",
            "status": "COMPLETE",
            "rounds": raw_rounds,
        }],
    }


def raw_standings():
    return [
        {
            "rank": 1,
            "player": {"id": 1, "best_identifier": "Alice"},
            "user_event_status": {
                "id": 1001, "best_identifier": "Alice#1", "registration_status": "ACTIVE",
                "matches_won": 1, "matches_lost": 0, "matches_drawn": 0, "total_match_points": 3,
            },
        },
        {
            "rank": 2,
            "player": {"id": 2, "best_identifier": "Bob"},
            "user_event_status": {
                "id": 1002, "best_identifier": "Bob#2", "registration_status": "ACTIVE",
                "matches_won": 0, "matches_lost": 1, "matches_drawn": 0, "total_match_points": 0,
            },
        },
    ]


def raw_match(match_id=500):
    return {
        "id": match_id,
        "status": "COMPLETE",
        "table_number": 1,
        "winning_player": 1,
        "games_won_by_winner": 2,
        "games_won_by_loser": 0,
        "match_is_intentional_draw": False,
        "match_is_unintentional_draw": False,
        "match_is_bye": False,
        "match_is_loss": False,
        "is_ghost_match": False,
        "is_feature_match": False,
        "created_at": "2026-09-13T19:00:00Z",
        "updated_at": "2026-09-13T19:10:00Z",
        "player_match_relationships": [
            {"player": {"id": 1, "best_identifier": "Alice"}, "user_event_status": {"best_identifier": "Alice#1"}},
            {"player": {"id": 2, "best_identifier": "Bob"}, "user_event_status": {"best_identifier": "Bob#2"}},
        ],
    }

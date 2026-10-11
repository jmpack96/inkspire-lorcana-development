from sqlalchemy import create_engine, event, text

from lorcana.playhub.query_repository import PlayHubQueryRepository


def test_match_categories_share_one_scan_and_preserve_null_semantics():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for name in ("events", "stores", "players"):
            conn.execute(text(f"CREATE TABLE playhub_{name} (id INTEGER)"))
            conn.execute(text(f"INSERT INTO playhub_{name} VALUES (1)"))
        conn.execute(text("CREATE TABLE playhub_matches (participant_count INTEGER)"))
        conn.execute(text("INSERT INTO playhub_matches VALUES (2), (2), (3), (NULL), (1)"))
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cur, stmt, params, ctx, many: statements.append(stmt))
    with engine.connect() as conn:
        result = PlayHubQueryRepository().database_counts(conn)
    assert result == dict(events=1, stores=1, players=1, matches=5,
                          two_player_matches=2, multiplayer_matches=1, unknown_participants=1)
    assert len(statements) == 4
    assert sum("FROM playhub_matches" in s for s in statements) == 1

from uuid import uuid4
from sqlalchemy import create_engine, event, text
from lorcana.ratings.repository import RatingRepository


def test_combined_rank_counts_preserve_ties_and_run_scope():
    engine = create_engine('sqlite://')
    run, other = uuid4(), uuid4()
    with engine.begin() as c:
        c.execute(text('CREATE TABLE rating_current (rating_run_id TEXT, rating FLOAT)'))
        for rating in (1500, 1500, 1600, 1400):
            c.execute(text('INSERT INTO rating_current VALUES (:run, :rating)'), {'run': run.hex, 'rating': rating})
        c.execute(text('INSERT INTO rating_current VALUES (:run, 2000)'), {'run': other.hex})
    sql = []
    event.listen(engine, 'before_cursor_execute', lambda c, cur, stmt, params, ctx, many: sql.append(stmt))
    with engine.connect() as c:
        assert RatingRepository().player_rank_stats(c, run, 1500) == (4, 1, 1)
    assert len(sql) == 1

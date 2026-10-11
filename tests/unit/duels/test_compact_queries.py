from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy.dialects import postgresql

from lorcana.duels.summary import DuelsSummaryRepository
from lorcana.duels.practice_repository import PracticeRepository
from lorcana.duels.repository import DuelsRepository


class Result:
    def mappings(self): return self
    def all(self): return []
    def one_or_none(self): return None
    def __iter__(self): return iter(())


class Capture:
    def __init__(self): self.sql = []
    def execution_options(self, **kwargs): return self
    def execute(self, statement):
        self.sql.append(str(statement.compile(dialect=postgresql.dialect())))
        return Result()


def test_summary_and_practice_queries_do_not_read_normalized_json():
    connection = Capture()
    now = datetime.now(timezone.utc)
    member = uuid4()
    DuelsSummaryRepository().history(connection, member_ids=[member], since=now, until=now)
    repo = PracticeRepository()
    repo.history(connection, member_id=member, since=now, until=now, ranked=None, limit=100)
    repo.opening_evidence(connection, member_id=member, normalization_ids=[uuid4()])
    assert len(connection.sql) == 3
    for sql in connection.sql:
        assert 'duels_normalizations.normalized' not in sql
        assert 'duels_read_models' in sql
    assert 'LATERAL' not in connection.sql[0]
    assert 'duels_connections.member_id' in connection.sql[2]


def test_processed_replay_checks_select_no_large_payloads():
    connection = Capture()
    repo = DuelsRepository()
    repo.latest_replay(connection, uuid4(), 'game', include_body=False)
    repo.get_normalization(connection, uuid4(), 'parser', include_body=False)
    repo.get_feature_set(connection, uuid4(), 'features', include_body=False)
    for sql in connection.sql:
        assert 'compressed_bytes' not in sql
        assert 'duels_normalizations.normalized' not in sql
        assert 'duels_feature_sets.features' not in sql

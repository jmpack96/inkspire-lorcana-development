from io import StringIO

from alembic import command
from alembic.config import Config


def test_upgrade_and_downgrade_generate_valid_concurrent_sql(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/lorcana_test")
    output = StringIO()
    cfg = Config("alembic.ini", output_buffer=output)
    command.upgrade(cfg, "20261004_0011:20261011_0012", sql=True)
    sql = output.getvalue()
    assert sql.count("CREATE INDEX CONCURRENTLY") == 4
    assert "jsonb_build_object('type', 'interval', 'seconds', 3600)" in sql
    assert "NULL" not in sql
    assert sql.index("COMMIT;") < sql.index("CREATE INDEX CONCURRENTLY")
    assert "priority = 16" in sql
    output.seek(0)
    output.truncate()
    command.downgrade(cfg, "20261011_0012:20261004_0011", sql=True)
    assert output.getvalue().count("DROP INDEX CONCURRENTLY") == 4

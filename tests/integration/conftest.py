from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config

from lorcana.config import _validated_postgres_url, sqlalchemy_postgres_url
from lorcana.db.engine import create_database_engine


def _test_database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is not configured")
    _validated_postgres_url(value, name="TEST_DATABASE_URL")
    database_name = urlsplit(value).path.strip("/").lower()
    if "test" not in database_name and os.environ.get("LORCANA_ALLOW_DESTRUCTIVE_DB_TESTS") != "1":
        pytest.fail("Refusing destructive integration tests: TEST_DATABASE_URL database name must contain 'test'")
    return sqlalchemy_postgres_url(value)


@pytest.fixture(scope="session")
def migrated_database_url():
    url = _test_database_url()
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    try:
        yield url
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old


@pytest.fixture
def db_engine(migrated_database_url):
    engine = create_database_engine(migrated_database_url)
    try:
        yield engine
    finally:
        engine.dispose()

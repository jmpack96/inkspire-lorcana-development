"""PostgreSQL engine construction."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def create_database_engine(database_url: str) -> Engine:
    """Construct an engine without opening a connection."""
    return create_engine(
        database_url,
        pool_size=int(os.environ.get("LORCANA_DB_POOL_SIZE", "3")),
        max_overflow=int(os.environ.get("LORCANA_DB_MAX_OVERFLOW", "1")),
        pool_timeout=float(os.environ.get("LORCANA_DB_POOL_TIMEOUT", "15")),
        pool_pre_ping=True,
        pool_recycle=300,
    )

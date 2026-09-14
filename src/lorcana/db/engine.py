"""PostgreSQL engine construction."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def create_database_engine(database_url: str) -> Engine:
    """Construct an engine without opening a connection."""
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=300,
    )

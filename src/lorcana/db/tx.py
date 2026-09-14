"""Explicit transaction boundary helper."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.engine import Connection, Engine


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """Open one transaction and commit/rollback at the context boundary."""
    with engine.begin() as connection:
        yield connection

"""Database table definitions used by repositories and Alembic metadata."""

from lorcana.db.schema import catalog, coach, duels, identity, jobs, playhub, ratings  # noqa: F401

__all__ = ["catalog", "coach", "duels", "identity", "jobs", "playhub", "ratings"]

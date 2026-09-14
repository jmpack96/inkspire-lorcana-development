from pathlib import Path


SRC = Path(__file__).parents[2] / "src" / "lorcana"


def _python_texts(root: Path):
    for path in root.rglob("*.py"):
        yield path, path.read_text()


def test_sqlite_is_only_used_by_one_time_transfer_module():
    users = []
    for path, text in _python_texts(SRC):
        if "import sqlite3" in text or "from sqlite3" in text:
            users.append(path.relative_to(SRC).as_posix())
    assert users == ["db/transfer_sqlite.py"]


def test_discord_interface_does_not_own_sql_or_scheduling():
    forbidden = ("sqlalchemy", "ScheduledJobService", "RatingRepository", "PlayHubRepository")
    violations = []
    for path, text in _python_texts(SRC / "interfaces" / "discord"):
        for token in forbidden:
            if token in text:
                violations.append((path.name, token))
    assert violations == []


def test_legacy_runtime_package_is_gone():
    assert not (SRC / "legacy").exists()

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import pytest

from lorcana.duels.weekly import aggregate_weekly, team_opponent_losses, latest_weekly_boundary, previous_weekly_boundary, WeeklyDuelsService
from lorcana.interfaces.discord.weekly_duels_views import weekly_views


def row(ours, theirs, result, n=1):
    return dict(member_id="a", your_deck_colors=ours, opponent_deck_colors=theirs,
                result=result, games=n, team_observers=2)


def test_counts_all_decks_internal_games_ties_unknown_and_zero_activity():
    rows = aggregate_weekly({"a": "Jacob", "b": "Ben"}, [
        row(["ruby", "sapphire"], ["amber", "steel"], "lost", 2),
        row(["steel", "amber"], ["amethyst", "emerald"], "loss", 2),
        row(["sapphire", "ruby"], None, "won"),
        row(None, None, "loss"), row(None, None, None), row(None, None, "tie")])
    jacob = rows[1]
    assert rows[0]["games"] == 0
    assert jacob["games"] == 8
    assert "most_losses" not in jacob
    assert next(d for d in jacob["decks"] if d["colors"] == "Ruby/Sapphire")["win"] == 1
    assert next(d for d in jacob["decks"] if d["colors"] == "Unknown")["unknown"] == 1


@pytest.mark.parametrize("now, expected", [
    ("2026-10-04T12:59:00+00:00", "2026-09-27T13:00:00+00:00"),
    ("2026-10-04T13:00:00+00:00", "2026-10-04T13:00:00+00:00"),
    ("2026-11-01T14:00:00+00:00", "2026-11-01T14:00:00+00:00")])
def test_sunday_nine_eastern_boundary(now, expected):
    assert latest_weekly_boundary(datetime.fromisoformat(now)) == datetime.fromisoformat(expected)


def test_scheduled_weeks_remain_adjacent_across_dst():
    end = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
    assert end - previous_weekly_boundary(end) == timedelta(hours=169)


class Repository:
    def roster(self, c, slug, duels_only=False):
        return [dict(member_id="a", preferred_display_name="Jacob")]
    def viewer(self, c, uid):
        return "a" if uid == 1 else "outsider"
    def results(self, c, **kwargs):
        self.window = kwargs
        return []
    def coverage(self, c, ids):
        return []


@contextmanager
def connection():
    yield None


def test_authorization_and_half_open_rolling_window_without_catalog():
    repo = Repository()
    now = datetime(2026, 10, 4, 13, tzinfo=timezone.utc)
    service = WeeklyDuelsService(repository=repo, connection_factory=connection,
                                 team_slug="inkspire", clock=lambda: now)
    with pytest.raises(ValueError, match="Link your Discord"):
        service.report(2)
    report = service.report(1)
    assert repo.window["since"] == now - timedelta(days=7)
    assert repo.window["until"] == now - timedelta(microseconds=1)
    assert report["missing"] == ["Jacob"]
    assert service.report()["rows"] == report["rows"]


def test_large_team_is_paginated_without_dropping_decks():
    rows = aggregate_weekly({"a": "Jacob"}, [row(["ruby", "sapphire"], ["amber", "steel"], "loss")])
    report = dict(start=datetime.now(timezone.utc), end=datetime.now(timezone.utc),
                  rows=rows * 100, missing=[], opponent_losses=dict(colors=["Amber/Steel"], count=1, unknown=0))
    pages = weekly_views(report)
    assert len(pages) > 1
    assert sum(p.description.count("Ruby/Sapphire: 0-1-0") for p in pages) == 100
    assert all(len(p.description) <= 4096 for p in pages)


def test_team_losses_use_opponent_colors_across_players_and_own_decks():
    results = [row(["ruby", "sapphire"], ["amber", "steel"], "loss", 3),
               dict(row(["amethyst", "ruby"], ["steel", "amber"], "lost", 4), member_id="b"),
               row(["amber", "steel"], ["emerald", "steel"], "win", 20),
               row(["ruby", "sapphire"], ["amethyst", "emerald"], "loss", 6),
               row(None, None, "loss", 2)]
    losses = team_opponent_losses({"a": "Jacob", "b": "Ben"}, results)
    assert losses == dict(colors=["Amber/Steel"], count=7, unknown=2)
    results.append(dict(row(None, ["amethyst", "emerald"], "loss"), member_id="b"))
    assert team_opponent_losses({"a": "Jacob", "b": "Ben"}, results)["colors"] == ["Amber/Steel", "Amethyst/Emerald"]
    report = dict(start=datetime.now(timezone.utc), end=datetime.now(timezone.utc),
                  rows=aggregate_weekly({"a": "Jacob", "b": "Ben"}, results),
                  missing=[], opponent_losses=losses)
    text = "\n".join(p.description for p in weekly_views(report))
    assert text.count("Team — most losses against") == 1
    assert "Amber/Steel — 7 losses" in text
    assert "Most losses across all decks" not in text

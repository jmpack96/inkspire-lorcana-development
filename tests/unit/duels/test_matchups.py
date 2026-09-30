from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from lorcana.duels.matchups import MatchupService, current_set, COLOR_PAIRS
from lorcana.interfaces.discord.application import DiscordApplication
from lorcana.interfaces.discord.matchup_views import matchup_views

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
META = {"sets": [{"code": "12", "name": "Test current set", "released_at": "2026-08-01"},
                 {"code": "13", "name": "Future set", "released_at": "2026-11-01"},
                 {"code": "P1", "name": "Promo", "released_at": "2026-09-01"}]}


def test_set_period_excludes_future_and_promos_and_rolls_forward():
    assert current_set(META, NOW)["code"] == 12
    assert current_set(META, datetime(2026, 11, 1, tzinfo=timezone.utc))["code"] == 13
    assert current_set(META, NOW)["start"] == datetime(2026, 8, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="catalog-enqueue-refresh"):
        current_set({}, NOW)
    assert len(COLOR_PAIRS) == 15


@contextmanager
def reader():
    yield None


class Repository:
    def __init__(self):
        self.a, self.b = uuid4(), uuid4()
        self.rows = []
        self.viewer_id = self.a
        self.metadata = META
        self.result_calls = []

    def roster(self, c, slug):
        return [{"member_id": self.a, "preferred_display_name": "Jacob"},
                {"member_id": self.b, "preferred_display_name": "Michael"}]

    def viewer(self, c, uid):
        return self.viewer_id

    def catalog(self, c):
        return {"metadata_json": self.metadata, "imported_at": NOW}

    def coverage(self, c, member_ids):
        return [{"member_id": self.a, "last_sync": NOW}]

    def results(self, c, **kwargs):
        self.result_calls.append(kwargs)
        return self.rows

    def result(self, **kwargs):
        row = dict(member_id=self.a, result="win", games=4, team_observers=1,
                   your_deck_colors=["sapphire", "ruby"], opponent_deck_colors=["steel", "emerald"],
                   queue_id="infinity-bo1", queue_name="Infinity", mode="ranked", match_format="bo1", ranked=True)
        row.update(kwargs)
        return row


def service(repo):
    return MatchupService(repository=repo, connection_factory=reader, team_slug="inkspire", clock=lambda: NOW)


def test_player_team_color_filters_and_queues_stay_separate():
    r = Repository()
    r.rows = [r.result(), r.result(result="loss", games=2),
              r.result(member_id=r.b, your_deck_colors=["amber", "steel"]),
              r.result(queue_id="core-bo1", queue_name="Core"),
              r.result(queue_id=None, queue_name=None), r.result(ranked=False)]
    report = service(r).report(123, team=True, opponent="Emerald/Steel")
    assert len(report["rows"]) == 5
    assert any(x["ours"] == "Amber/Steel" for x in report["rows"])
    first = report["rows"][0]
    assert first["win"] == 4 and first["loss"] == 2
    assert "Infinity" in first["queue"]
    assert any("Format unknown" in x["queue"] for x in report["rows"])
    assert report["synced"] == 1 and report["missing"] == ["Michael"]
    assert len(service(r).report(123, player=str(r.b))["rows"]) == 1
    assert service(r).report(123, opponent="Amber/Ruby")["rows"] == []
    assert r.result_calls[-1]["since"] == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_unauthorized_viewer_and_forged_player_never_query_results():
    r = Repository()
    with pytest.raises(ValueError, match="active member"):
        service(r).report(123, player=str(uuid4()))
    with pytest.raises(ValueError, match="dropdown"):
        service(r).report(123, player="Jacob")
    r.viewer_id = None
    with pytest.raises(ValueError, match="Link your Discord"):
        service(r).report(123, team=True)
    assert not r.result_calls
    with pytest.raises(ValueError):
        service(r).choices(123)


def test_internal_games_excluded_even_on_player_report_and_unknown_separate():
    r = Repository()
    r.rows = [r.result(team_observers=2), r.result(result=None, games=1), r.result(result="draw", games=2)]
    report = service(r).report(123)
    assert report["internal"] == 4
    assert report["rows"][0]["unknown"] == 1
    assert report["rows"][0]["draw"] == 2
    view = matchup_views(report)[0]
    assert "0% wins" in view.fields[0].value
    assert "1 unknown" in view.fields[0].value


def test_pages_are_short_and_application_is_private():
    r = Repository()
    r.rows = [r.result(queue_id=f"core-{i}", queue_name=f"Core {i}") for i in range(14)]
    app = DiscordApplication(ratings=None, playhub=None, teams=None, matchups=service(r))
    response = app.matchup_report(123, team=True)
    assert not response.ephemeral and len(response.embeds) == 2
    assert app.matchup_report(123).ephemeral
    assert app.matchup_report(123, player=str(r.b)).ephemeral
    assert app.matchup_report(123, team=True, opponent="invalid").ephemeral
    assert all(len(p.fields) <= 6 for p in response.embeds)
    assert "Test current set" in response.embeds[0].description
    assert app.matchup_report(123, player="invalid").ephemeral
    assert len(app.matchup_players(123)) == 2


def test_team_table_condenses_rows_without_combining_queue_records():
    r = Repository()
    r.rows = [r.result(), r.result(result="loss", games=2),
              r.result(result="draw", games=1), r.result(result=None, games=1),
              r.result(member_id=r.b, games=3),
              r.result(queue_id="core-bo1", queue_name="Core", games=5)]
    report = service(r).report(123, team=True)
    pages = matchup_views(report)
    assert len(pages) == 1
    infinity = pages[0].description
    assert not pages[0].fields
    assert "Ru/Sa" in infinity and "Em/St" in infinity
    assert "7-2-1" in infinity and "70%" in infinity
    # N counts unknowns too; the separate ? column makes the denominator clear.
    assert next(line for line in infinity.splitlines() if line.startswith("Ru/Sa")).split() == ["Ru/Sa", "Em/St", "7-2-1", "70%", "11", "1"]
    assert "player" not in report["rows"][0]
    assert "Jacob" not in infinity
    assert "Player" not in infinity
    assert "Core" in infinity
    assert infinity.count("```") == 4
    assert "Am Amber" in infinity and "Ay Amethyst" in infinity


def test_team_tables_paginate_fit_discord_and_sanitize_labels():
    r = Repository()
    r.rows = [r.result(your_deck_colors=[a, b], games=i + 1)
              for i, (a, b) in enumerate(pair.split("/") for pair in COLOR_PAIRS)]
    report = service(r).report(123, team=True)
    report["period"]["name"] = "@everyone\n```\t" + "x" * 100
    report["rows"][0].update(ours="Unknown", win=0, loss=0, draw=0, unknown=16)
    pages = matchup_views(report)
    assert len(pages) == 2
    assert sum(len(p.description.split("```\n")[1].split("\n```", 1)[0].splitlines()) - 1
               for p in pages) == 15
    assert "—" in pages[0].description and "?" in pages[0].description
    for page in pages:
        assert page.description.count("```") == 2
        assert "@everyone" not in page.description
        assert len(page.description) <= 4096
        assert len(page.title) + len(page.description) + len(page.footer) < 6000


def test_empty_team_report_has_no_empty_table():
    report = service(Repository()).report(123, team=True)
    pages = matchup_views(report)
    assert len(pages) == 1
    assert "No matching synced games" in pages[0].description
    assert "```" not in pages[0].description


def test_team_totals_are_weighted_and_player_reports_stay_individual():
    r = Repository()
    r.rows = [r.result(games=9), r.result(result="loss", games=1),
              r.result(member_id=r.b, result="loss", games=2),
              r.result(member_id=r.b, result=None, games=3),
              r.result(member_id=r.b, team_observers=2, games=4)]
    combined = service(r).report(123, team=True, opponent="Emerald/Steel")
    assert len(combined["rows"]) == 1
    totals = combined["rows"][0]
    assert (totals["win"], totals["loss"], totals["draw"], totals["unknown"]) == (9, 3, 0, 3)
    assert combined["internal"] == 4
    assert "75%" in matchup_views(combined)[0].description
    jacob = service(r).report(123)
    michael = service(r).report(123, player=str(r.b))
    assert jacob["rows"][0]["player"] == "Jacob"
    assert (jacob["rows"][0]["win"], jacob["rows"][0]["loss"]) == (9, 1)
    assert michael["rows"][0]["player"] == "Michael"
    assert michael["rows"][0]["loss"] == 2

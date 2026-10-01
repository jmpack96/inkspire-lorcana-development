from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from lorcana.duels.summary import DuelsSummaryService, validated_mulligan
from lorcana.interfaces.discord.application import DiscordApplication
from lorcana.interfaces.discord.duels_summary_views import summary_views

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def evidence(count=3):
    cards = [{"id": str(i)} for i in range(7)]
    return dict(game={"perspective": 1, "player_names": {"1": "Me", "2": "Other"}},
                starting_hand=cards, parser_warnings=[],
                mulligan=dict(count=count, kept=cards[count:], sent_back=cards[:count],
                              drawn=[{"id": "new"}] * count))


@pytest.mark.parametrize("count", [0, 3, 7])
def test_valid_mulligans_include_zero(count):
    assert validated_mulligan(evidence(count)) == count


@pytest.mark.parametrize("change", [
    {"mulligan": None}, {"starting_hand": []}, {"parser_warnings": ["inconsistent"]},
    {"game": {"perspective": None}}, {"game": {"perspective": 1, "player_names": {"1": "a", "2": "b", "3": "c"}}},
])
def test_unavailable_or_untrusted_openings_are_excluded(change):
    source = evidence()
    source.update(change)
    assert validated_mulligan(source) is None


def test_bad_counts_and_inconsistent_cards_are_excluded():
    for count in (True, "3", -1, 8):
        source = evidence()
        source["mulligan"]["count"] = count
        assert validated_mulligan(source) is None
    source = evidence()
    source["mulligan"]["sent_back"] = [{"id": "wrong"}] * 3
    assert validated_mulligan(source) is None
    source = evidence()
    source["mulligan"]["drawn"] = []
    assert validated_mulligan(source) is None


@contextmanager
def reader():
    yield None


class Repository:
    def __init__(self):
        self.a, self.b = uuid4(), uuid4()
        self.duels_members = {self.a, self.b}
        self.viewer_id = self.a
        self.rows = []
        self.calls = []

    def roster(self, c, slug, *, duels_only=False):
        roster = [{"member_id": self.a, "preferred_display_name": "Jacob"},
                {"member_id": self.b, "preferred_display_name": "Ben"}]
        return [r for r in roster if not duels_only or r["member_id"] in self.duels_members]

    def viewer(self, c, uid):
        return self.viewer_id

    def catalog(self, c):
        return {"metadata_json": {"sets": [{"code": "12", "name": "Set", "released_at": "2026-08-01"}]}, "imported_at": NOW}

    def coverage(self, c, ids):
        return [{"member_id": self.a, "last_sync": NOW}]

    def history(self, c, **kwargs):
        self.calls.append(kwargs)
        return self.rows

    def row(self, colors=None, opening=None, member=None):
        return {"member_id": member or self.a, "your_deck_colors": colors,
                "evidence": opening}


def service(repo):
    return DuelsSummaryService(repository=repo, connection_factory=reader,
                               team_slug="inkspire", clock=lambda: NOW)


def test_team_summary_averages_evidence_only_and_preserves_no_data_players():
    r = Repository()
    r.rows = [r.row(["ruby", "sapphire"], evidence(0)),
              r.row(["sapphire", "ruby"], evidence(6)),
              r.row(["amber", "steel"]), r.row(None), r.row(None, evidence(3))]
    report = service(r).report(123)
    jacob = next(row for row in report["rows"] if row["player"] == "Jacob")
    assert jacob == dict(player="Jacob", games=5, known_colors=3, top_count=2,
                         top_colors=["Ruby/Sapphire"], mulligan_average=3, sample=3)
    ben = next(row for row in report["rows"] if row["player"] == "Ben")
    assert ben["games"] == 0 and ben["mulligan_average"] is None
    assert ben["top_colors"] == []
    assert report["synced"] == 1 and report["members"] == 2
    assert r.calls[0]["since"] == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert set(r.calls[0]["member_ids"]) == {r.a, r.b}
    page = summary_views(report)[0]
    assert "🔴🔵" in page.description and "3/5" in page.description and "2/3" in page.description
    assert "3.00" in page.description and "—" in page.description
    assert "starting_hand" not in page.description


def test_tied_colors_are_all_reported_and_unauthorized_users_never_query_history():
    r = Repository()
    r.rows = [r.row(["ruby", "sapphire"]), r.row(["emerald", "steel"])]
    report = service(r).report(123)
    jacob = next(row for row in report["rows"] if row["player"] == "Jacob")
    assert jacob["top_colors"] == ["Emerald/Steel", "Ruby/Sapphire"]
    assert "tied:" in summary_views(report)[0].description
    r.viewer_id = uuid4()
    before = len(r.calls)
    with pytest.raises(ValueError, match="active member"):
        service(r).report(999)
    assert len(r.calls) == before


def test_application_public_success_private_error_and_pages_fit():
    r = Repository()
    app = DiscordApplication(ratings=None, playhub=None, teams=None, duels_summary=service(r))
    response = app.duels_summary_report(123)
    assert not response.ephemeral and response.embeds
    r.viewer_id = None
    assert app.duels_summary_report(999).ephemeral
    report = service(Repository()).report(123)
    source = report["rows"][0]
    report["rows"] = [dict(deepcopy(source), player="@everyone ```\n" + "x" * 100,
                          top_colors=["Ruby/Sapphire", "Emerald/Steel"]) for _ in range(15)]
    pages = summary_views(report)
    assert len(pages) == 1
    for page in pages:
        assert "@everyone" not in page.description
        assert page.description.count("```") == 2
        assert len(page.description) <= 4096
        assert len(page.title) + len(page.description) + len(page.footer) < 6000


def test_summary_filters_members_and_allows_unconfigured_teammate_to_view():
    r = Repository()
    r.duels_members = {r.a}
    r.viewer_id = r.b
    r.rows = [r.row(["ruby", "sapphire"], evidence()),
              r.row(["amber", "steel"], evidence(), member=r.b)]
    report = service(r).report(123)
    assert [row["player"] for row in report["rows"]] == ["Jacob"]
    assert report["members"] == report["synced"] == 1
    assert r.calls[-1]["member_ids"] == [r.a]
    r.duels_members = set()
    report = service(r).report(123)
    assert report["rows"] == [] and report["members"] == 0
    assert "configured Duels connection" in summary_views(report)[0].description


def test_summary_twenty_rows_per_page_and_early_split_for_long_ties():
    from lorcana.duels.matchups import COLOR_PAIRS, COLORS
    report = service(Repository()).report(123)
    row = report["rows"][0]
    report["rows"] = [dict(row, player=f"Player {i}", top_colors=["Ruby/Sapphire"]) for i in range(45)]
    pages = summary_views(report)
    assert len(pages) == 3
    assert len(pages[0].description.split("```\n")[1].split("\n```", 1)[0].splitlines()) == 21
    for row in report["rows"]:
        row.update(player="LongName" * 20, top_colors=list(COLOR_PAIRS) + list(COLORS),
                   games=10**12, known_colors=10**12, top_count=10**12, sample=10**12)
    pages = summary_views(report)
    assert len(pages) > 3
    for page in pages:
        assert len(page.description) <= 4096
        assert len(page.title) + len(page.description) + len(page.footer) < 6000

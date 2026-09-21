from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from lorcana.analytics.service import CommandUsageEntry, CommandUsageSummary
from lorcana.interfaces.discord.application import DiscordApplication
from lorcana.playhub.query_service import DatabaseStatus, LatestImport, SetChampionshipEvent
from lorcana.ratings.query_service import (
    LeaderboardEntry,
    PlayerHistory,
    PlayerProfile,
    PlayerSearchResult,
    PublishedLeaderboard,
    PublishedRatingRun,
    RecordSummary,
)
from lorcana.teams.query_service import TeamLeaderboard, TeamLeaderboardMember


class Jobs:
    def __init__(self):
        self.calls = []

    def enqueue(self, kind, **kwargs):
        self.calls.append((kind, kwargs))
        return type(
            "Enqueued",
            (),
            {
                "job_id": "00000000-0000-0000-0000-000000000401",
                "created": True,
            },
        )()

NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)
RUN = PublishedRatingRun(
    publication_name="global_elo",
    rating_run_id=UUID("00000000-0000-0000-0000-000000000001"),
    published_at=NOW,
    algorithm="elo",
    algorithm_version="elo_v2_2player_only",
    policy_version="global_elo_v1",
    input_count=10,
    player_count=2,
    ordered_input_digest="abc",
)


class Ratings:
    def __init__(self):
        self.matches = ()
        self.profile = None
        self.history = None
        self.board = PublishedLeaderboard(publication=RUN, entries=())

    def search_players(self, query):
        self.query = query
        return self.matches

    def player_profile(self, player_id):
        self.player_id = player_id
        return self.profile

    def player_history(self, player_id):
        self.history_player_id = player_id
        return self.history

    def competitive_leaderboard(self, *, minimum_matches, limit):
        self.board_args = (minimum_matches, limit)
        return self.board


class PlayHub:
    def __init__(self):
        self.events = ()
        self.status = DatabaseStatus(1, 2, 3, 4, 4, 0, 0, None)

    def database_status(self):
        return self.status

    def houston_set_championships(self, set_name):
        self.set_name = set_name
        return self.events


class Teams:
    def __init__(self):
        self.slug = None

    def leaderboard(self, slug):
        self.slug = slug
        return TeamLeaderboard(
            team_id=UUID("00000000-0000-0000-0000-000000000010"),
            team_slug=slug,
            team_name="Inkspire",
            publication=RUN,
            members=(TeamLeaderboardMember(
                team_rank=1,
                member_id=UUID("00000000-0000-0000-0000-000000000011"),
                preferred_display_name="Jacob",
                playhub_player_id=7504,
                role="member",
                rating=1600.0,
                matches_played=10,
                wins=6,
                losses=4,
                draws=0,
                peak_rating=1620.0,
            ),),
            recent_events=(),
            recent_event_days=7,
        )


class Usage:
    def summary(self, *, days):
        self.days = days
        return CommandUsageSummary(
            days=days,
            invocations=3,
            unique_users=2,
            failures=1,
            entries=(
                CommandUsageEntry(
                    command_name="player",
                    invocations=3,
                    unique_users=2,
                    failures=1,
                    average_duration_ms=25,
                    team_selector_invocations=0,
                ),
            ),
        )


def app():
    ratings, playhub, teams = Ratings(), PlayHub(), Teams()
    return DiscordApplication(ratings=ratings, playhub=playhub, teams=teams), ratings, playhub, teams


def test_player_not_found_and_ambiguous_are_ephemeral():
    application, ratings, _, _ = app()
    missing = application.player("nobody")
    assert missing.ephemeral is True
    assert "No player found" in missing.content

    ratings.matches = (
        PlayerSearchResult(1, "A", "a", 1500.0, 5),
        PlayerSearchResult(2, "B", "b", 1510.0, 6),
    )
    ambiguous = application.player("a")
    assert ambiguous.ephemeral is True
    assert ambiguous.embeds[0].title == "Multiple players found"


def test_single_player_returns_profile_embed():
    application, ratings, _, _ = app()
    ratings.matches = (PlayerSearchResult(1, "A", "a", 1500.0, 5),)
    ratings.profile = PlayerProfile(
        publication=RUN,
        player_id=1,
        display_name="A",
        username="a",
        has_rating=True,
        rating=1500.0,
        peak_rating=1510.0,
        matches_played=5,
        wins=3,
        losses=2,
        draws=0,
        rank=2,
        total_rated=10,
        percentile=80.0,
        recent_10=RecordSummary(3, 2, 0),
        recent_25=RecordSummary(3, 2, 0),
        rating_change_25=0.0,
        average_opponent_rating=1490.0,
        expected_score_total=2.5,
        actual_score_total=3.0,
        performance_vs_expected=0.5,
    )
    response = application.player("A")
    assert response.ephemeral is True
    assert response.embeds[0].title == "a"
    assert ratings.player_id == 1


def test_single_player_history_is_ephemeral():
    application, ratings, _, _ = app()
    ratings.matches = (PlayerSearchResult(1, "A", "a", 1500.0, 5),)
    ratings.history = PlayerHistory(
        publication=RUN,
        player_id=1,
        display_name="A",
        username="a",
        events=(),
    )

    response = application.player_history("A")

    assert response.ephemeral is True
    assert response.embeds[0].title == "a — Player History"
    assert ratings.history_player_id == 1


def test_leaderboard_empty_and_populated_paths():
    application, ratings, _, _ = app()
    assert "No players meet" in application.leaderboard(minimum_matches=20).content
    entry = LeaderboardEntry(1, 1, "A", "a", 1600.0, 20, 12, 8, 0, 1620.0)
    ratings.board = PublishedLeaderboard(
        publication=RUN,
        entries=(entry,),
        eligible_players=1,
        minimum_matches=20,
    )
    response = application.leaderboard(minimum_matches=20, limit=25)
    assert response.embeds[0].title == "Global Lorcana Elo Leaderboard"
    assert ratings.board_args == (20, 25)


def test_database_status_set_champs_and_team_are_delegated():
    application, _, playhub, teams = app()
    assert application.database_status().embeds[0].title == "Global Lorcana Database"
    assert "No Houston" in application.set_championships("Fabled").content

    playhub.events = (SetChampionshipEvent(
        event_id=1,
        event_name="Championship",
        start_datetime=NOW,
        end_datetime=None,
        player_count=32,
        capacity=64,
        source_url=None,
        store_id="store-1",
        store_name="Store",
        city="Houston",
        state_region="TX",
        country="US",
        latitude=None,
        longitude=None,
    ),)
    assert application.set_championships("Fabled").embeds[0].title == "Fabled Set Championships"
    assert application.team_leaderboard().embeds[0].title == "Inkspire Elo Leaderboard"
    assert teams.slug == "inkspire"


def test_team_players_returns_linked_default_team_members():
    application, _, _, teams = app()

    members = application.team_players()

    assert [member.preferred_display_name for member in members] == ["Jacob"]
    assert [member.playhub_player_id for member in members] == [7504]
    assert teams.slug == "inkspire"


def test_command_stats_is_private_and_delegates_requested_period():
    usage = Usage()
    application = DiscordApplication(
        ratings=Ratings(),
        playhub=PlayHub(),
        teams=Teams(),
        usage=usage,
    )

    response = application.command_stats(days=14)

    assert response.ephemeral is True
    assert response.embeds[0].title == "Discord Command Usage — 14 Days"
    assert "3" in response.embeds[0].description
    assert usage.days == 14


def test_refresh_elo_queues_unique_immediate_job_and_is_private():
    jobs = Jobs()
    application = DiscordApplication(
        ratings=Ratings(),
        playhub=PlayHub(),
        teams=Teams(),
        jobs=jobs,
    )

    response = application.refresh_elo()

    assert response.ephemeral is True
    assert response.content.startswith("Queued an immediate Global Elo refresh")
    assert "current and previous" in response.content
    kind, values = jobs.calls[0]
    assert kind == "ratings.build_publish"
    assert values["resource_key"] == "global_elo"
    assert values["payload"] == {
        "publication_name": "global_elo",
        "policy": "global",
    }
    assert values["idempotency_key"].startswith(
        "ratings.build_publish:global_elo:discord:"
    )


def test_refresh_elo_reports_unconfigured_queue():
    application, _, _, _ = app()

    response = application.refresh_elo()

    assert response.ephemeral is True
    assert "not configured" in response.content


class Identity:
    def __init__(self, member=None):
        self.member = member

    def member_for_discord_user(self, discord_user_id):
        self.discord_user_id = discord_user_id
        return self.member


class CoachRequests:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def request(self, *, member_id, game_id):
        from lorcana.coach.request_service import CoachRequestError
        self.called = (member_id, game_id)
        if self.error:
            raise CoachRequestError(self.error)
        return self.result


class CoachReports:
    def __init__(self, report=None):
        self.report = report

    def latest_report_for_game(self, member_id, game_id):
        self.called = (member_id, game_id)
        return self.report


def test_coach_commands_require_linked_identity_and_remain_ephemeral():
    from types import SimpleNamespace
    member_id = UUID("00000000-0000-0000-0000-000000000099")
    identity = Identity(SimpleNamespace(member_id=member_id, preferred_display_name="Jacob"))
    requests = CoachRequests(SimpleNamespace(
        job_id=UUID("00000000-0000-0000-0000-000000000098"),
        created=True,
        game_id="game-1",
    ))
    reports = CoachReports()
    ratings, playhub, teams = Ratings(), PlayHub(), Teams()
    application = DiscordApplication(
        ratings=ratings,
        playhub=playhub,
        teams=teams,
        identity=identity,
        coach_requests=requests,
        coach=reports,
    )

    queued = application.coach_request(1234, "game-1")
    assert queued.ephemeral is True
    assert "Queued Coach analysis" in queued.content
    assert requests.called == (member_id, "game-1")

    missing = application.coach_report(1234, "game-1")
    assert missing.ephemeral is True
    assert "No completed Coach report" in missing.content


def test_coach_report_renders_persisted_result_without_analysis_call():
    from types import SimpleNamespace
    member_id = UUID("00000000-0000-0000-0000-000000000097")
    report = SimpleNamespace(
        analysis_run_id=UUID("00000000-0000-0000-0000-000000000096"),
        finding_count=2,
        content="# Lorcana Game Review\n\nPersisted result.",
    )
    application = DiscordApplication(
        ratings=Ratings(),
        playhub=PlayHub(),
        teams=Teams(),
        identity=Identity(SimpleNamespace(member_id=member_id, preferred_display_name="Jacob")),
        coach_requests=None,
        coach=CoachReports(report),
    )
    response = application.coach_report(1234, "game-1")
    assert response.ephemeral is True
    assert response.embeds[0].title == "Lorcana Coach Report"
    assert "Persisted result" in response.embeds[0].description
    assert "2 findings" in response.embeds[0].footer


def test_unlinked_discord_user_cannot_request_or_read_coach_data():
    application = DiscordApplication(
        ratings=Ratings(), playhub=PlayHub(), teams=Teams(),
        identity=Identity(None), coach_requests=CoachRequests(), coach=CoachReports(),
    )
    assert "not linked" in application.coach_request(999, "game-1").content
    assert "not linked" in application.coach_report(999, "game-1").content

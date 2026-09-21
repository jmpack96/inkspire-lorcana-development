"""Discord command use-cases without a dependency on discord.py.

The actual gateway adapter is intentionally thin: it defers interactions,
runs one of these synchronous application methods in a worker thread, and
renders the returned response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from lorcana.analytics.service import DiscordUsageService
from lorcana.interfaces.discord.views import (
    EmbedSpec,
    coach_report_views,
    database_status_view,
    leaderboard_view,
    player_profile_view,
    player_search_view,
    set_championship_views,
    team_leaderboard_view,
    player_history_views,
    command_usage_view,
)
from lorcana.coach.request_service import CoachRequestError, CoachRequestService
from lorcana.coach.service import CoachService
from lorcana.identity.query_service import IdentityQueryService
from lorcana.jobs.kinds import enqueue_rating_build
from lorcana.jobs.service import JobQueue
from lorcana.playhub.query_service import PlayHubQueryService
from lorcana.ratings.query_service import RatingQueryService
from lorcana.teams.query_service import TeamLeaderboardMember, TeamQueryService


@dataclass(frozen=True)
class DiscordResponse:
    content: str | None = None
    embeds: tuple[EmbedSpec, ...] = field(default_factory=tuple)
    ephemeral: bool = False

    def __post_init__(self) -> None:
        if self.content is None and not self.embeds:
            raise ValueError("DiscordResponse requires content or at least one embed")


class DiscordApplication:
    """Synchronous command behavior shared by any Discord gateway adapter."""

    def __init__(
        self,
        *,
        ratings: RatingQueryService,
        playhub: PlayHubQueryService,
        teams: TeamQueryService,
        default_team_slug: str = "inkspire",
        identity: IdentityQueryService | None = None,
        coach_requests: CoachRequestService | None = None,
        coach: CoachService | None = None,
        usage: DiscordUsageService | None = None,
        jobs: JobQueue | None = None,
    ) -> None:
        if not default_team_slug.strip():
            raise ValueError("default_team_slug must not be empty")
        self.ratings = ratings
        self.playhub = playhub
        self.teams = teams
        self.identity = identity
        self.coach_requests = coach_requests
        self.coach = coach
        self.usage = usage
        self.jobs = jobs
        self.default_team_slug = default_team_slug.strip().lower()

    def player(self, query: str) -> DiscordResponse:
        matches = self.ratings.search_players(query)
        if not matches:
            return DiscordResponse(
                content=f"No player found matching `{query}`.",
                ephemeral=True,
            )
        if len(matches) > 1:
            return DiscordResponse(
                embeds=(player_search_view(query, matches),),
                ephemeral=True,
            )
        profile = self.ratings.player_profile(matches[0].player_id)
        if profile is None:
            return DiscordResponse(
                content="That player could not be loaded.",
                ephemeral=True,
            )
        return DiscordResponse(
            embeds=(player_profile_view(profile),),
            ephemeral=True,
        )

    def player_history(self, query: str) -> DiscordResponse:
        matches = self.ratings.search_players(query)

        if not matches:
            return DiscordResponse(
                content=f"No player found matching `{query}`.",
                ephemeral=True,
            )

        if len(matches) > 1:
            return DiscordResponse(
                embeds=(player_search_view(query, matches),),
                ephemeral=True,
            )

        history = self.ratings.player_history(matches[0].player_id)

        if history is None:
            return DiscordResponse(
                content="That player's history could not be loaded.",
                ephemeral=True,
            )

        return DiscordResponse(
            embeds=player_history_views(history),
            ephemeral=True,
        )

    def team_players(self) -> tuple[TeamLeaderboardMember, ...]:
        """Return the default team's members that can be used for player lookup."""
        data = self.teams.leaderboard(self.default_team_slug)
        return tuple(
            member
            for member in data.members
            if member.playhub_player_id is not None
        )

    def leaderboard(self, *, minimum_matches: int = 20, limit: int = 25) -> DiscordResponse:
        data = self.ratings.competitive_leaderboard(
            minimum_matches=minimum_matches,
            limit=limit,
        )
        if not data.entries:
            return DiscordResponse(
                content=f"No players meet the {minimum_matches}-match minimum."
            )
        return DiscordResponse(embeds=(leaderboard_view(data),))

    def team_leaderboard(self, *, team_slug: str | None = None) -> DiscordResponse:
        data = self.teams.leaderboard(team_slug or self.default_team_slug)
        return DiscordResponse(embeds=(team_leaderboard_view(data),))

    def command_stats(self, *, days: int = 30) -> DiscordResponse:
        if self.usage is None:
            return DiscordResponse(
                content="Discord command analytics are not configured.",
                ephemeral=True,
            )
        return DiscordResponse(
            embeds=(command_usage_view(self.usage.summary(days=days)),),
            ephemeral=True,
        )

    def refresh_elo(self) -> DiscordResponse:
        """Queue an immediate global Elo refresh for an administrator."""
        if self.jobs is None:
            return DiscordResponse(
                content="The Elo refresh queue is not configured on this bot.",
                ephemeral=True,
            )
        result = enqueue_rating_build(
            self.jobs,
            publication_name="global_elo",
            policy="global",
            generation=f"discord:{uuid4()}",
        )
        state = "Queued" if result.created else "Already queued"
        return DiscordResponse(
            content=(
                f"{state} an immediate Global Elo refresh. Job `{result.job_id}`. "
                "The worker will publish only if eligible match data changed and will "
                "prune Elo runs older than the current and previous publications."
            ),
            ephemeral=True,
        )

    def database_status(self) -> DiscordResponse:
        return DiscordResponse(embeds=(database_status_view(self.playhub.database_status()),))

    def set_championships(self, set_name: str) -> DiscordResponse:
        events = self.playhub.houston_set_championships(set_name)
        if not events:
            return DiscordResponse(
                content=f"No Houston Set Championships were found for **{set_name}**."
            )
        return DiscordResponse(embeds=set_championship_views(set_name, events))

    def coach_request(self, discord_user_id: int, game_id: str) -> DiscordResponse:
        if self.identity is None or self.coach_requests is None:
            return DiscordResponse(
                content="Coach analysis is not configured on this bot yet.",
                ephemeral=True,
            )
        member = self.identity.member_for_discord_user(discord_user_id)
        if member is None:
            return DiscordResponse(
                content="Your Discord account is not linked to a Lorcana member profile yet.",
                ephemeral=True,
            )
        try:
            result = self.coach_requests.request(member_id=member.member_id, game_id=game_id)
        except CoachRequestError as error:
            return DiscordResponse(content=str(error), ephemeral=True)
        state = "Queued" if result.created else "Already queued or completed"
        return DiscordResponse(
            content=(
                f"{state} Coach analysis for game `{result.game_id}`. "
                f"Job `{result.job_id}`. Use `/coachreport` with this game ID to view the latest completed report."
            ),
            ephemeral=True,
        )

    def coach_report(self, discord_user_id: int, game_id: str) -> DiscordResponse:
        if self.identity is None or self.coach is None:
            return DiscordResponse(
                content="Coach reports are not configured on this bot yet.",
                ephemeral=True,
            )
        member = self.identity.member_for_discord_user(discord_user_id)
        if member is None:
            return DiscordResponse(
                content="Your Discord account is not linked to a Lorcana member profile yet.",
                ephemeral=True,
            )
        report = self.coach.latest_report_for_game(member.member_id, game_id)
        if report is None:
            return DiscordResponse(
                content=f"No completed Coach report was found for game `{game_id}`.",
                ephemeral=True,
            )
        return DiscordResponse(embeds=coach_report_views(game_id, report), ephemeral=True)

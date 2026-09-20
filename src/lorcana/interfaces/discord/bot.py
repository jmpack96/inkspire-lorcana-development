"""discord.py gateway adapter for the Lorcana platform.

No scheduling, ingestion, rating calculation, or SQL belongs here.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from lorcana.analytics.service import DiscordUsageService
from lorcana.bootstrap import ApplicationResources
from lorcana.catalog.service import CatalogService
from lorcana.coach.request_service import CoachRequestService
from lorcana.coach.service import CoachService
from lorcana.duels.query_service import DuelsQueryService
from lorcana.identity.query_service import IdentityQueryService
from lorcana.jobs.service import JobQueue
from lorcana.notifications.live_events import LiveEventAlertService
from lorcana.interfaces.discord.application import DiscordApplication, DiscordResponse
from lorcana.interfaces.discord.views import EmbedSpec
from lorcana.playhub.query_service import PlayHubQueryService
from lorcana.ratings.query_service import RatingQueryService
from lorcana.teams.query_service import TeamQueryService

logger = logging.getLogger(__name__)


def _load_discord() -> tuple[Any, Any]:
    try:
        import discord
        from discord import app_commands
    except ImportError as error:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Discord support is not installed. Install lorcana-platform[bot]."
        ) from error
    return discord, app_commands


def _to_discord_embed(discord: Any, spec: EmbedSpec):
    embed = discord.Embed(title=spec.title, description=spec.description)
    for field in spec.fields:
        embed.add_field(name=field.name, value=field.value, inline=field.inline)
    if spec.footer:
        embed.set_footer(text=spec.footer)
    return embed


async def _send_response(
    interaction: Any,
    discord: Any,
    response: DiscordResponse,
) -> None:
    embeds = [_to_discord_embed(discord, spec) for spec in response.embeds]

    if not embeds:
        await interaction.followup.send(
            response.content,
            ephemeral=response.ephemeral,
        )
        return

    if len(embeds) == 1:
        await interaction.followup.send(
            content=response.content,
            embed=embeds[0],
            ephemeral=response.ephemeral,
        )
        return

    # Add page numbers without changing the pure EmbedSpec presentation model.
    for index, embed in enumerate(embeds):
        existing_footer = embed.footer.text if embed.footer else None
        page_text = f"Page {index + 1}/{len(embeds)}"

        if existing_footer:
            embed.set_footer(text=f"{existing_footer} • {page_text}")
        else:
            embed.set_footer(text=page_text)

    class EmbedPaginator(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=300)
            self.index = 0
            self._sync_buttons()

        def _sync_buttons(self) -> None:
            self.previous.disabled = self.index == 0
            self.next.disabled = self.index == len(embeds) - 1

        @discord.ui.button(
            label="Previous",
            style=discord.ButtonStyle.secondary,
        )
        async def previous(
            self,
            button_interaction: discord.Interaction,
            button: discord.ui.Button,
        ) -> None:
            self.index -= 1
            self._sync_buttons()

            await button_interaction.response.edit_message(
                embed=embeds[self.index],
                view=self,
            )

        @discord.ui.button(
            label="Next",
            style=discord.ButtonStyle.secondary,
        )
        async def next(
            self,
            button_interaction: discord.Interaction,
            button: discord.ui.Button,
        ) -> None:
            self.index += 1
            self._sync_buttons()

            await button_interaction.response.edit_message(
                embed=embeds[self.index],
                view=self,
            )

    await interaction.followup.send(
        content=response.content,
        embed=embeds[0],
        view=EmbedPaginator(),
        ephemeral=response.ephemeral,
    )


def create_bot(resources: ApplicationResources):
    discord, app_commands = _load_discord()
    coach_requests = None
    coach_service = None
    usage = DiscordUsageService.from_engine(resources.engine)
    live_event_alerts = LiveEventAlertService.from_engine(resources.engine)
    identity = IdentityQueryService.from_engine(resources.engine)
    if resources.settings.coach_analyzer_name is not None:
        coach_requests = CoachRequestService(
            duels=DuelsQueryService.from_engine(resources.engine),
            catalog=CatalogService.from_engine(resources.engine),
            jobs=JobQueue.from_engine(resources.engine),
            analyzer_name=resources.settings.coach_analyzer_name,
            analyzer_generation=resources.settings.coach_analyzer_generation,
        )
        coach_service = CoachService.from_engine(resources.engine)
    application = DiscordApplication(
        ratings=RatingQueryService.from_engine(resources.engine),
        playhub=PlayHubQueryService.from_engine(resources.engine),
        teams=TeamQueryService.from_engine(resources.engine),
        default_team_slug=resources.settings.discord_team_slug,
        identity=identity,
        coach_requests=coach_requests,
        coach=coach_service,
        usage=usage,
    )

    class LorcanaBot(discord.Client):
        def __init__(self) -> None:
            super().__init__(intents=discord.Intents.default())
            self.tree = app_commands.CommandTree(self)
            self.live_event_delivery_task: asyncio.Task | None = None

        async def setup_hook(self) -> None:
            synced = await self.tree.sync()
            logger.info("Synced %d Discord slash commands", len(synced))
            if getattr(resources.settings, "live_event_channel_id", None) is not None:
                self.live_event_delivery_task = asyncio.create_task(
                    self.deliver_live_event_links()
                )

        async def deliver_live_event_links(self) -> None:
            await self.wait_until_ready()
            while not self.is_closed():
                announcement = await asyncio.to_thread(live_event_alerts.next_pending)
                if announcement is None:
                    await asyncio.sleep(5)
                    continue
                try:
                    eligible = await asyncio.to_thread(
                        live_event_alerts.event_is_eligible,
                        resources.settings.discord_team_slug,
                        announcement.event_id,
                    )
                    if not eligible:
                        raise RuntimeError("event is no longer actively happening")
                    channel = await self.fetch_channel(announcement.channel_id)
                    message = await channel.send(announcement.event_url)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.exception(
                        "Failed to deliver live event %s to channel %s",
                        announcement.event_id,
                        announcement.channel_id,
                    )
                    await asyncio.to_thread(
                        live_event_alerts.mark_failed,
                        announcement,
                        error,
                    )
                    continue
                await asyncio.to_thread(
                    live_event_alerts.mark_sent,
                    announcement.announcement_id,
                    int(message.id),
                )

        async def close(self) -> None:
            try:
                if self.live_event_delivery_task is not None:
                    self.live_event_delivery_task.cancel()
                await super().close()
            finally:
                resources.close()

    bot = LorcanaBot()

    async def record_usage(
        interaction: Any,
        *,
        command_name: str,
        invocation_mode: str,
        succeeded: bool,
        started_at: float,
    ) -> None:
        duration_ms = max(0, round((time.perf_counter() - started_at) * 1000))
        guild_id = None if interaction.guild_id is None else int(interaction.guild_id)
        try:
            await asyncio.to_thread(
                usage.record,
                command_name=command_name,
                invocation_mode=invocation_mode,
                discord_user_id=int(interaction.user.id),
                guild_id=guild_id,
                succeeded=succeeded,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.exception("Could not record Discord command usage")

    async def execute(
        interaction: Any,
        call,
        *args,
        ephemeral: bool = False,
        invocation_mode: str = "direct",
        track_usage: bool = True,
        command_name: str | None = None,
        **kwargs,
    ) -> None:
        started_at = time.perf_counter()
        await interaction.response.defer(ephemeral=ephemeral)
        try:
            response = await asyncio.to_thread(call, *args, **kwargs)
        except Exception:
            logger.exception("Discord command failed")
            await interaction.followup.send(
                "There was an error loading that request.",
                ephemeral=True,
            )
            if track_usage:
                await record_usage(
                    interaction,
                    command_name=command_name or interaction.command.name,
                    invocation_mode=invocation_mode,
                    succeeded=False,
                    started_at=started_at,
                )
            return
        await _send_response(interaction, discord, response)
        if track_usage:
            await record_usage(
                interaction,
                command_name=command_name or interaction.command.name,
                invocation_mode=invocation_mode,
                succeeded=True,
                started_at=started_at,
            )

    async def choose_team_player(
        interaction: Any,
        call: Callable[[str], DiscordResponse],
        *,
        prompt: str,
        command_name: str,
    ) -> None:
        """Show the default team roster and run ``call`` for the selected player."""
        started_at = time.perf_counter()
        await interaction.response.defer(ephemeral=True)
        try:
            members = await asyncio.to_thread(application.team_players)
            members = tuple(
                sorted(
                    members,
                    key=lambda member: member.preferred_display_name.casefold(),
                )
            )
        except Exception:
            logger.exception("Discord team player selector failed")
            await interaction.followup.send(
                "There was an error loading the team roster.",
                ephemeral=True,
            )
            await record_usage(
                interaction,
                command_name=command_name,
                invocation_mode="team_selector",
                succeeded=False,
                started_at=started_at,
            )
            return

        if not members:
            await interaction.followup.send(
                "No linked players were found on the team roster. Use the optional "
                "`query` argument to look up a player directly.",
                ephemeral=True,
            )
            await record_usage(
                interaction,
                command_name=command_name,
                invocation_mode="team_selector",
                succeeded=False,
                started_at=started_at,
            )
            return

        # Discord permits 25 options per string select and five component rows.
        # Splitting the roster preserves a full-team selector as the team grows.
        if len(members) > 125:
            await interaction.followup.send(
                "The team roster is too large for a Discord selection menu. Use the "
                "optional `query` argument to look up a player directly.",
                ephemeral=True,
            )
            await record_usage(
                interaction,
                command_name=command_name,
                invocation_mode="team_selector",
                succeeded=False,
                started_at=started_at,
            )
            return

        chunks = [members[index:index + 25] for index in range(0, len(members), 25)]

        class TeamPlayerSelect(discord.ui.Select):
            def __init__(self, chunk, index: int) -> None:
                placeholder = "Choose a team player"
                if len(chunks) > 1:
                    placeholder += f" ({index + 1}/{len(chunks)})"
                super().__init__(
                    placeholder=placeholder,
                    min_values=1,
                    max_values=1,
                    options=[
                        discord.SelectOption(
                            label=member.preferred_display_name[:100],
                            value=str(member.playhub_player_id),
                            description=f"Play Hub player ID {member.playhub_player_id}",
                        )
                        for member in chunk
                    ],
                )

            async def callback(self, select_interaction: discord.Interaction) -> None:
                await execute(
                    select_interaction,
                    call,
                    self.values[0],
                    ephemeral=True,
                    track_usage=False,
                )

        class TeamPlayerView(discord.ui.View):
            def __init__(self) -> None:
                super().__init__(timeout=300)
                for index, chunk in enumerate(chunks):
                    self.add_item(TeamPlayerSelect(chunk, index))

        await interaction.followup.send(
            prompt,
            view=TeamPlayerView(),
            ephemeral=True,
        )
        await record_usage(
            interaction,
            command_name=command_name,
            invocation_mode="team_selector",
            succeeded=True,
            started_at=started_at,
        )

    @bot.tree.command(name="player", description="Look up a Lorcana player's stats.")
    @app_commands.describe(query="Optional Play Hub name, username, or player ID")
    async def player(interaction: discord.Interaction, query: str | None = None) -> None:
        if query:
            await execute(
                interaction,
                application.player,
                query,
                invocation_mode="direct_query",
            )
            return
        await choose_team_player(
            interaction,
            application.player,
            prompt="Choose a team player to view their stats.",
            command_name="player",
        )

    @bot.tree.command(
        name="playerhistory",
        description="Show a Lorcana player's tournament and match history.",
    )
    @app_commands.describe(
        query="Optional Play Hub name, username, or player ID"
    )
    async def playerhistory(
        interaction: discord.Interaction,
        query: str | None = None,
    ) -> None:
        if not query:
            await choose_team_player(
                interaction,
                application.player_history,
                prompt="Choose a team player to view their tournament and match history.",
                command_name="playerhistory",
            )
            return
        await execute(
            interaction,
            application.player_history,
            query,
            invocation_mode="direct_query",
        )

    @bot.tree.command(name="leaderboard", description="Show the global Lorcana Elo leaderboard.")
    @app_commands.describe(
        minimum_matches="Minimum rated matches required to appear on the leaderboard.",
        limit="Number of players to show.",
    )
    async def leaderboard(
        interaction: discord.Interaction,
        minimum_matches: app_commands.Range[int, 1, 500] = 20,
        limit: app_commands.Range[int, 1, 25] = 25,
    ) -> None:
        await execute(
            interaction,
            application.leaderboard,
            minimum_matches=minimum_matches,
            limit=limit,
        )

    @bot.tree.command(name="teamleaderboard", description="Show the team Elo leaderboard.")
    async def teamleaderboard(interaction: discord.Interaction) -> None:
        await execute(interaction, application.team_leaderboard)

    @bot.tree.command(
        name="commandstats",
        description="Show recent Discord command usage (administrators only).",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(days="Number of days to include.")
    async def commandstats(
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 365] = 30,
    ) -> None:
        await execute(
            interaction,
            application.command_stats,
            days=days,
            ephemeral=True,
        )

    @commandstats.error
    async def commandstats_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "You need the Administrator permission to use `/commandstats`.",
                ephemeral=True,
            )
            return
        raise error

    @bot.tree.command(name="dbstatus", description="Show the current Global Lorcana database status.")
    async def dbstatus(interaction: discord.Interaction) -> None:
        await execute(interaction, application.database_status)

    @bot.tree.command(
        name="setchamps",
        description="Find Set Championships in Houston for a Lorcana set.",
    )
    @app_commands.describe(set_name="Lorcana set name, such as Fabled")
    async def setchamps(interaction: discord.Interaction, set_name: str) -> None:
        await execute(interaction, application.set_championships, set_name)


    @bot.tree.command(name="coach", description="Queue a private Coach analysis for one of your Duels games.")
    @app_commands.describe(game_id="Duels game ID")
    async def coach(interaction: discord.Interaction, game_id: str) -> None:
        await execute(
            interaction,
            application.coach_request,
            int(interaction.user.id),
            game_id,
            ephemeral=True,
        )

    @bot.tree.command(name="coachreport", description="View your latest completed Coach report for a Duels game.")
    @app_commands.describe(game_id="Duels game ID")
    async def coachreport(interaction: discord.Interaction, game_id: str) -> None:
        await execute(
            interaction,
            application.coach_report,
            int(interaction.user.id),
            game_id,
            ephemeral=True,
        )

    @bot.event
    async def on_ready() -> None:
        logger.info("Discord bot connected as %s", bot.user)

    return bot


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    resources = ApplicationResources.from_env()
    try:
        token = resources.settings.require_discord_bot_token()
        bot = create_bot(resources)
        bot.run(token)
    except Exception:
        resources.close()
        raise


if __name__ == "__main__":  # pragma: no cover
    main()

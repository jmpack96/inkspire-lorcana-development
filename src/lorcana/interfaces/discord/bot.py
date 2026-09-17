"""discord.py gateway adapter for the Lorcana platform.

No scheduling, ingestion, rating calculation, or SQL belongs here.
"""

import asyncio
import logging
from typing import Any

from lorcana.bootstrap import ApplicationResources
from lorcana.catalog.service import CatalogService
from lorcana.coach.request_service import CoachRequestService
from lorcana.coach.service import CoachService
from lorcana.duels.query_service import DuelsQueryService
from lorcana.identity.query_service import IdentityQueryService
from lorcana.jobs.service import JobQueue
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


async def _send_response(interaction: Any, discord: Any, response: DiscordResponse) -> None:
    embeds = [_to_discord_embed(discord, spec) for spec in response.embeds]
    if not embeds:
        await interaction.followup.send(response.content, ephemeral=response.ephemeral)
        return

    # Multiple embed pages are sent individually so commands such as /setchamps
    # never approach Discord's aggregate embed payload limits.
    for index, embed in enumerate(embeds):
        kwargs = {"embed": embed, "ephemeral": response.ephemeral}
        if index == 0 and response.content is not None:
            kwargs["content"] = response.content
        await interaction.followup.send(**kwargs)


def create_bot(resources: ApplicationResources):
    discord, app_commands = _load_discord()
    coach_requests = None
    coach_service = None
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
    )

    class LorcanaBot(discord.Client):
        def __init__(self) -> None:
            super().__init__(intents=discord.Intents.default())
            self.tree = app_commands.CommandTree(self)

        async def setup_hook(self) -> None:
            synced = await self.tree.sync()
            logger.info("Synced %d Discord slash commands", len(synced))

        async def close(self) -> None:
            try:
                await super().close()
            finally:
                resources.close()

    bot = LorcanaBot()

    async def execute(interaction: Any, call, *args, ephemeral: bool = False, **kwargs) -> None:
        await interaction.response.defer(ephemeral=ephemeral)
        try:
            response = await asyncio.to_thread(call, *args, **kwargs)
        except Exception:
            logger.exception("Discord command failed")
            await interaction.followup.send(
                "There was an error loading that request.",
                ephemeral=True,
            )
            return
        await _send_response(interaction, discord, response)

    @bot.tree.command(name="player", description="Look up a Lorcana player's stats.")
    @app_commands.describe(query="Play Hub name, username, or player ID")
    async def player(interaction: discord.Interaction, query: str) -> None:
        await execute(interaction, application.player, query)

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

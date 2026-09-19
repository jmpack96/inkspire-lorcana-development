"""Pure Discord-facing presentation models; no discord.py dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from lorcana.playhub.query_service import DatabaseStatus, SetChampionshipEvent
from lorcana.ratings.query_service import PlayerProfile, PlayerSearchResult, PublishedLeaderboard, PlayerHistory, PlayerHistoryMatch
from lorcana.teams.query_service import TeamLeaderboard


@dataclass(frozen=True)
class EmbedField:
    name: str
    value: str
    inline: bool = False


@dataclass(frozen=True)
class EmbedSpec:
    title: str
    description: str | None = None
    fields: tuple[EmbedField, ...] = field(default_factory=tuple)
    footer: str | None = None


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit - 3] + "..."


def _player_history_match_line(match: PlayerHistoryMatch) -> str:
    result = {
        "WIN": "W",
        "LOSS": "L",
        "DRAW": "D",
        "BYE": "BYE",
        "UNKNOWN": "?",
    }.get(match.result, match.result)

    round_name = (
        f"R{match.round_number}"
        if match.round_number is not None
        else "Match"
    )

    if match.result == "BYE":
        opponent = "Bye"
    elif (
        match.opponent_id is None
        and match.opponent_name is None
        and match.opponent_username is None
    ):
        opponent = "Unknown"
    else:
        opponent = (
            match.opponent_name
            or match.opponent_username
            or f"Player {match.opponent_id}"
        )

    line = f"**{round_name} {result}** vs {opponent}"

    if (
        match.player_score is not None
        and match.opponent_score is not None
    ):
        line += f" {match.player_score}-{match.opponent_score}"

    if match.intentional_draw:
        line += " • ID"

    if match.rated:
        line += " • `Elo`"

    return line


def _player_history_event_field(event) -> EmbedField:
    header_parts = [
        _record(event.wins, event.losses, event.draws),
    ]

    if event.placement is not None:
        header_parts.append(f"#{event.placement}")

    header_parts.append(
        f"Elo {event.rated_matches}/{len(event.matches)}"
    )

    match_lines = [
        _player_history_match_line(match)
        for match in event.matches
    ]

    value = (
        " • ".join(header_parts)
        + "\n"
        + "\n".join(match_lines)
    )

    if event.source_url:
        value += f"\n[View event]({event.source_url})"

    return EmbedField(
        name=_truncate(
            f"{_discord_timestamp(event.start_datetime, 'D')} — "
            f"{event.event_name}",
            256,
        ),
        value=_truncate(value, 1024),
        inline=False,
    )


def player_history_views(
    history: PlayerHistory,
) -> tuple[EmbedSpec, ...]:
    player_name = (
        history.username
        or history.display_name
        or f"Player {history.player_id}"
    )

    if not history.events:
        return (
            EmbedSpec(
                title=f"{player_name} — Player History",
                description=(
                    f"**Play Hub ID:** `{history.player_id}`\n"
                    "No recorded Play Hub matches were found."
                ),
            ),
        )

    fields = [
        _player_history_event_field(event)
        for event in history.events
    ]

    events_per_page = 5
    pages = []

    for start in range(0, len(fields), events_per_page):
        page_fields = fields[start:start + events_per_page]

        pages.append(
            EmbedSpec(
                title=f"{player_name} — Player History",
                description=(
                    f"**{len(history.events)} events** • "
                    f"**{history.total_matches} matches** • "
                    f"**{history.rated_matches} rated**\n"
                    f"Play Hub ID: `{history.player_id}`"
                ),
                fields=tuple(page_fields),
                footer=history.publication.policy_version,
            )
        )

    return tuple(pages)
def _discord_timestamp(value: datetime | None, style: str = "F") -> str:
    if value is None:
        return "Date unknown"
    if value.tzinfo is None or value.utcoffset() is None:
        return value.isoformat()
    return f"<t:{int(value.timestamp())}:{style}>"


def _player_name(display_name: str | None, username: str | None, player_id: int) -> str:
    name = display_name or f"Player {player_id}"
    if username and username != name:
        return f"{name} ({username})"
    return name


def _record(wins: int, losses: int, draws: int) -> str:
    return f"{wins}-{losses}-{draws}"


def database_status_view(status: DatabaseStatus) -> EmbedSpec:
    latest = status.latest_import
    latest_text = "No imports recorded"
    if latest is not None:
        when = latest.completed_at or latest.started_at
        latest_text = f"Event {latest.event_id} — {latest.status}\n{_discord_timestamp(when, 'R')}"
    return EmbedSpec(
        title="Global Lorcana Database",
        description="Current PostgreSQL source-data status",
        fields=(
            EmbedField("Events", f"{status.events:,}", True),
            EmbedField("Stores", f"{status.stores:,}", True),
            EmbedField("Players", f"{status.players:,}", True),
            EmbedField("Matches", f"{status.matches:,}", True),
            EmbedField("Confirmed 1v1", f"{status.two_player_matches:,}", True),
            EmbedField("3+ Player Anomalies", f"{status.multiplayer_matches:,}", True),
            EmbedField("Participant Count Unknown", f"{status.unknown_participants:,}", True),
            EmbedField("Latest Import", latest_text, False),
        ),
    )


def player_search_view(query: str, matches: tuple[PlayerSearchResult, ...]) -> EmbedSpec:
    lines = []
    for match in matches:
        rating = (
            f"Elo {match.rating:.0f} | {match.matches_played} matches"
            if match.rating is not None
            else "No current Elo"
        )
        lines.append(
            f"**{_player_name(match.display_name, match.username, match.player_id)}**\n"
            f"ID: `{match.player_id}` | {rating}"
        )
    return EmbedSpec(
        title="Multiple players found",
        description="\n\n".join(lines),
        footer="Run /player again using the player ID.",
    )


def player_profile_view(profile: PlayerProfile) -> EmbedSpec:
    username = profile.username or profile.display_name or f"Player {profile.player_id}"
    display_name = profile.display_name or "Unknown"
    description = f"**Name:** {display_name}\n**Play Hub ID:** `{profile.player_id}`"
    if not profile.has_rating:
        return EmbedSpec(
            title=username,
            description=description,
            fields=(EmbedField("Elo", "No rating in the published Elo run", False),),
            footer=(
                f"{profile.publication.algorithm_version} • {profile.publication.policy_version} • "
                f"run {profile.publication.rating_run_id}"
            ),
        )

    fields = [
        EmbedField("Elo", f"**{profile.rating:.0f}**", True),
        EmbedField("Raw Global Rank", f"#{profile.rank:,} of {profile.total_rated:,}", True),
        EmbedField("Percentile", f"{profile.percentile:.1f}%", True),
        EmbedField("Record", _record(profile.wins, profile.losses, profile.draws), True),
        EmbedField("Matches", f"{profile.matches_played:,}", True),
        EmbedField("Peak Elo", f"{profile.peak_rating:.0f}", True),
    ]
    if profile.recent_10 is not None and profile.recent_25 is not None:
        fields.append(EmbedField(
            "Recent Form",
            f"Last 10: {_record(profile.recent_10.wins, profile.recent_10.losses, profile.recent_10.draws)}\n"
            f"Last 25: {_record(profile.recent_25.wins, profile.recent_25.losses, profile.recent_25.draws)}\n"
            f"Elo change: {profile.rating_change_25:+.1f}",
        ))
    schedule = (
        f"Average opponent Elo: **{profile.average_opponent_rating:.0f}**"
        if profile.average_opponent_rating is not None
        else "No opponent data"
    )
    fields.append(EmbedField("Strength of Schedule", schedule))
    fields.append(EmbedField(
        "Performance vs Expectation",
        f"Expected score: {profile.expected_score_total:.1f}\n"
        f"Actual score: {profile.actual_score_total:.1f}\n"
        f"Difference: **{profile.performance_vs_expected:+.1f}**",
    ))
    if profile.best_win is not None:
        best = profile.best_win
        opponent = best.opponent_name or best.opponent_username or f"Player {best.opponent_id}"
        value = f"**{opponent}** — {best.opponent_rating:.0f} Elo\n+{best.rating_change:.1f} Elo"
        if best.event_name:
            value += f"\n{best.event_name}"
        fields.append(EmbedField("Best Win", value))
    return EmbedSpec(
        title=username,
        description=description,
        fields=tuple(fields),
        footer=(
            f"{profile.publication.algorithm_version} • {profile.publication.policy_version} • "
            f"run {profile.publication.rating_run_id}"
        ),
    )


def leaderboard_view(data: PublishedLeaderboard) -> EmbedSpec:
    lines = []
    for player in data.entries:
        username = player.username or player.display_name or f"Player {player.player_id}"
        display = player.display_name or "Unknown"
        lines.append(
            f"**#{player.rank} — {username}**\n"
            f"Elo: **{player.rating:.0f}** • {display} • "
            f"{_record(player.wins, player.losses, player.draws)} • {player.matches_played} matches"
        )
    fields = ()
    if data.eligible_players is not None and data.minimum_matches is not None:
        fields = (EmbedField(
            "Eligibility",
            f"{data.eligible_players:,} players with at least {data.minimum_matches} rated matches",
        ),)
    return EmbedSpec(
        title="Global Lorcana Elo Leaderboard",
        description="\n\n".join(lines),
        fields=fields,
        footer=(
            f"{data.publication.algorithm_version} • {data.publication.policy_version} • "
            f"run {data.publication.rating_run_id}"
        ),
    )


def set_championship_views(set_name: str, events: tuple[SetChampionshipEvent, ...]) -> tuple[EmbedSpec, ...]:
    pages = []
    chunk_size = 10
    total_pages = (len(events) + chunk_size - 1) // chunk_size
    for start in range(0, len(events), chunk_size):
        fields = []
        for event in events[start:start + chunk_size]:
            date_text = f"{_discord_timestamp(event.start_datetime, 'F')}\n{_discord_timestamp(event.start_datetime, 'R')}"
            value = f"{date_text}\n**{event.event_name}**"
            if event.source_url:
                value += f"\n[View event]({event.source_url})"
            fields.append(EmbedField(event.store_name, value))
        page = start // chunk_size + 1
        pages.append(EmbedSpec(
            title=f"{set_name} Set Championships",
            description=f"**Houston, Texas**\nFound **{len(events)}** event{'' if len(events) == 1 else 's'}.",
            fields=tuple(fields),
            footer=f"Page {page}/{total_pages}" if total_pages > 1 else None,
        ))
    return tuple(pages)


def team_leaderboard_view(data: TeamLeaderboard) -> EmbedSpec:
    lines = []
    member_names = {}
    for member in data.members:
        if member.playhub_player_id is not None:
            member_names[member.playhub_player_id] = member.preferred_display_name
        if member.rating is None:
            player_text = (
                f" • Play Hub ID `{member.playhub_player_id}`"
                if member.playhub_player_id is not None
                else ""
            )
            lines.append(f"**— {member.preferred_display_name}**\nNo current Elo{player_text}")
        else:
            lines.append(
                f"**#{member.team_rank} — {member.preferred_display_name}**\n"
                f"Elo: **{member.rating:.0f}** • "
                f"{_record(member.wins, member.losses, member.draws)} • "
                f"{member.matches_played} matches • Peak {member.peak_rating:.0f}"
            )

    blocks = []
    for event in data.recent_events[:12]:
        names = [member_names.get(pid, f"Player {pid}") for pid in event.player_ids]
        blocks.append(
            f"**{_discord_timestamp(event.start_datetime, 'D')} — {event.name or f'Event {event.event_id}'}**\n"
            f"{', '.join(names) if names else 'No team members found'}"
        )
    activity = "\n\n".join(blocks) if blocks else f"No recorded team events in the last {data.recent_event_days} days."
    # Discord fields cap at 1024 characters; split only at block boundaries when possible.
    activity_fields = []
    current = ""
    for block in blocks:
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= 1024:
            current = candidate
        else:
            if current:
                activity_fields.append(current)
            current = block[:1021] + "..." if len(block) > 1024 else block
    if current:
        activity_fields.append(current)
    if not blocks:
        activity_fields = [activity]

    fields = tuple(
        EmbedField(
            "Team Events — Last 7 Days" if i == 0 else "Team Events — Continued",
            value,
        )
        for i, value in enumerate(activity_fields)
    )
    return EmbedSpec(
        title=f"{data.team_name} Elo Leaderboard",
        description="\n\n".join(lines),
        fields=fields,
        footer=(
            f"{data.publication.algorithm_version} • {data.publication.policy_version} • "
            f"run {data.publication.rating_run_id}"
        ),
    )


def coach_report_views(game_id: str, report) -> tuple[EmbedSpec, ...]:
    """Render a persisted Coach report without re-running the analyzer."""
    content = report.content.strip()
    if not content:
        content = "The persisted Coach report is empty."
    max_chars = 3800
    chunks: list[str] = []
    remaining = content
    while len(remaining) > max_chars:
        split_at = remaining.rfind("\n\n", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = remaining.rfind("\n", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = max_chars
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    total = len(chunks)
    return tuple(
        EmbedSpec(
            title="Lorcana Coach Report" if total == 1 else f"Lorcana Coach Report — {index}/{total}",
            description=chunk,
            footer=(
                f"Game {game_id} • {report.finding_count} finding"
                f"{'s' if report.finding_count != 1 else ''} • run {report.analysis_run_id}"
            ),
        )
        for index, chunk in enumerate(chunks, start=1)
    )

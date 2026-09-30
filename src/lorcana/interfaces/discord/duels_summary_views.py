"""Compact team summaries; no hands, replay details, or color legend."""
from lorcana.interfaces.discord.matchup_views import display_width, safe, short_colors
from lorcana.interfaces.discord.views import EmbedSpec


def summary_views(report):
    period = report["period"]
    intro = (f"**{safe(period['name'])}** · games since {period['start']:%b %d, %Y} UTC\n"
             f"{report['synced']}/{report['members']} players have completed a Duels sync.\n"
             "All queues, including team games. One observation per member/game.")
    footer = ("Played = top color count / games with known colors. "
              "Sample = validated mulligans / all games. Average includes zero-card mulligans; "
              "missing or invalid evidence excluded. Colors are not exact deck builds. "
              f"Catalog updated {report['catalog_updated']:%Y-%m-%d}.")
    if not report["rows"]:
        return (EmbedSpec("Team Duels summary", intro + "\nNo active team members.", footer=footer),)
    pages = []
    # Six players per page leaves room for tied color combinations and full names.
    for offset in range(0, len(report["rows"]), 6):
        rows = report["rows"][offset:offset + 6]
        cells = [["Player", "Main", "Played", "Avg mull", "Sample"]]
        ties = []
        for row in rows:
            colors = row["top_colors"]
            main = short_colors(colors[0]) if len(colors) == 1 else "Tie" if colors else "—"
            cells.append([safe(row["player"], 24), main,
                          f"{row['top_count']}/{row['known_colors']}",
                          f"{row['mulligan_average']:.2f}" if row["mulligan_average"] is not None else "—",
                          f"{row['sample']}/{row['games']}"])
            if len(colors) > 1:
                ties.append(f"**{safe(row['player'], 60)}** tied: " + " · ".join(short_colors(c) for c in colors))
        widths = [max(display_width(row[i]) for row in cells) for i in range(5)]
        lines = []
        for row in cells:
            lines.append(" ".join(value + " " * (widths[i] - display_width(value)) if i < 2
                                  else " " * (widths[i] - display_width(value)) + value
                                  for i, value in enumerate(row)).rstrip())
        table = "```\n" + "\n".join(lines) + "\n```"
        description = intro + "\n" + table
        if ties:
            description += "\n" + "\n".join(ties)
        pages.append(EmbedSpec("Team Duels summary", description, footer=footer))
    return tuple(pages)

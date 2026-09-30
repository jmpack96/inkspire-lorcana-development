"""One compact matchup page at a time; no technical inputs or replay details."""
from collections import defaultdict
from unicodedata import east_asian_width

from lorcana.interfaces.discord.views import EmbedField, EmbedSpec


def safe(value, length=100):
    return " ".join(str(value).replace("@", "＠").replace("`", "'").split())[:length]


INK_EMOJIS = {"Amber": "🟡", "Amethyst": "🟣", "Emerald": "🟢",
              "Ruby": "🔴", "Sapphire": "🔵", "Steel": "⚪", "Unknown": "❓"}


def short_colors(value):
    return "".join(INK_EMOJIS.get(color, "❓") for color in str(value).split("/"))


def display_width(value):
    # Emoji glyphs occupy two monospace columns, despite being one code point.
    return sum(2 if east_asian_width(char) in {"W", "F"} else 1 for char in value)


def team_table(rows):
    """Aligned text for Discord's monospace code blocks."""
    unknown = any(row["unknown"] for row in rows)
    headers = ["Deck", "Vs", "W-L-D", "Win%", "N"]
    if unknown:
        headers.append("?")
    cells = []
    for row in rows:
        decided = row["win"] + row["loss"] + row["draw"]
        values = [short_colors(row["ours"]), short_colors(row["theirs"]),
                  f"{row['win']}-{row['loss']}-{row['draw']}",
                  f"{100 * row['win'] / decided:.0f}%" if decided else "—",
                  str(decided + row["unknown"])]
        if unknown:
            values.append(str(row["unknown"]))
        cells.append(values)
    widths = [max(display_width(values[i]) for values in [headers, *cells]) for i in range(len(headers))]

    def line(values):
        return " ".join(value + " " * (widths[i] - display_width(value)) if i < 2
                        else " " * (widths[i] - display_width(value)) + value
                        for i, value in enumerate(values)).rstrip()

    return "```\n" + "\n".join(line(values) for values in [headers, *cells]) + "\n```"


def team_pages(report, description, footer):
    # Keep each queue together without combining any separately counted records.
    queues = defaultdict(list)
    for row in report["rows"]:
        queues[row["queue"]].append(row)
    pages = []
    sections = []
    page_rows = 0

    def page():
        return EmbedSpec(safe(report["title"], 200),
                         description + "\n" + "\n".join(sections), footer=footer)

    for queue, rows in queues.items():
        heading = f"**{safe(queue, 180)}**\n"
        offset = 0
        while offset < len(rows):
            count = min(12 - page_rows, len(rows) - offset)
            section = heading + team_table(rows[offset:offset + count])
            candidate = description + "\n" + "\n".join([*sections, section])
            while count > 1 and len(candidate) > 4096:
                count -= 1
                section = heading + team_table(rows[offset:offset + count])
                candidate = description + "\n" + "\n".join([*sections, section])
            if sections and len(candidate) > 4096:
                pages.append(page())
                sections, page_rows = [], 0
                continue
            sections.append(section)
            page_rows += count
            offset += count
            if page_rows == 12:
                pages.append(page())
                sections, page_rows = [], 0
    if sections:
        pages.append(page())
    return tuple(pages)


def matchup_views(report):
    period = report["period"]
    description = f"**{safe(period['name'])}** · games since {period['start']:%b %d, %Y} UTC"
    if report["opponent"]:
        description += f"\nAgainst **{report['opponent']}**"
    description += f"\n{report['synced']}/{report['members']} players have completed a Duels sync."
    if report["missing"]:
        description += "\nNo completed sync: " + ", ".join(safe(n, 35) for n in sorted(report["missing"])[:10])
    if report["internal"]:
        description += f"\nExcluded {report['internal']} team-v-team player results."
    footer = (f"Games, not matches. Win % includes draws; unknown outcomes excluded. "
              f"Set from catalog updated {report['catalog_updated']:%Y-%m-%d}. Small samples are descriptive.")
    rows = report["rows"]
    if not rows:
        return (EmbedSpec(safe(report["title"], 200), description + "\nNo matching synced games in this set period.", footer=footer),)
    if report["team"]:
        footer = ("Games, not matches. W-L-D = wins-losses-draws; N = all games; ? = unknown outcomes. "
                  "Win % includes draws, excludes unknowns. Results pooled across the team. "
                  f"Catalog updated {report['catalog_updated']:%Y-%m-%d}. Small samples are descriptive.")
        return team_pages(report, description, footer)
    pages = []
    for offset in range(0, len(rows), 6):
        fields = []
        for row in rows[offset:offset + 6]:
            n = row["win"] + row["loss"] + row["draw"]
            rate = f"{100 * row['win'] / n:.0f}% wins" if n else "win rate unavailable"
            value = f"**{row['win']}W–{row['loss']}L–{row['draw']}D · {rate} · {n} decided games**"
            if row["unknown"]:
                value += f" · {row['unknown']} unknown"
            value += f"\n{safe(row['queue'], 180)}"
            title = f"{row['ours']} vs {row['theirs']}"
            fields.append(EmbedField(title, value))
        pages.append(EmbedSpec(safe(report["title"], 200), description, tuple(fields), footer))
    return tuple(pages)

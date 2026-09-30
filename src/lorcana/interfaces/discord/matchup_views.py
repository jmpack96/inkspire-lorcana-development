"""One compact matchup page at a time; no technical inputs or replay details."""
from lorcana.interfaces.discord.views import EmbedField, EmbedSpec


def safe(value, length=100):
    return str(value).replace("@", "＠").replace("`", "'").replace("\n", " ")[:length]


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
            if report["team"]:
                title = f"{safe(row['player'], 60)} · {title}"
            fields.append(EmbedField(title, value))
        pages.append(EmbedSpec(safe(report["title"], 200), description, tuple(fields), footer))
    return tuple(pages)

"""Bounded weekly report pages, shared by slash command and scheduled delivery."""
from lorcana.duels.weekly import WEEKLY_TIMEZONE
from lorcana.interfaces.discord.matchup_views import safe
from lorcana.interfaces.discord.views import EmbedSpec


def weekly_views(report):
    start, end = (report[k].astimezone(WEEKLY_TIMEZONE) for k in ("start", "end"))
    intro = f"{start:%b %d, %Y %H:%M %Z} → {end:%b %d, %Y %H:%M %Z}\nAll queues, including team games; one count per player/game.\n"
    footer = "Decks grouped by colors, not exact builds. W-L-D; ? = unknown result. Win% = W/(W+L); excludes draws and unknown results. No minimum sample. Popularity ties sorted by color name. Imported history only."
    blocks = []
    for row in report["rows"]:
        blocks.append(f"**{safe(row['player'], 80)} — {row['games']} games**")
        for deck in row["decks"]:
            blocks.append(f"• {deck['colors']}: {deck['win']}-{deck['loss']}-{deck['draw']}" +
                          (f" · ? {deck['unknown']}" if deck['unknown'] else ""))
        blocks.append("")
    if not blocks:
        blocks = ["No team members have a configured Duels connection."]
    opponents = report["opponents"]
    def record_text(record, *, percentage=False):
        text = f"{record['colors']}: {record['win']}W–{record['loss']}L"
        if record["draw"]:
            text += f"–{record['draw']}D"
        if record["unknown"]:
            text += f" · ? {record['unknown']}"
        if percentage:
            text += f" · {record['win_percentage']:.1f}%"
        return text + f" · {record['games']} games"

    blocks.append("**Team — most losses against**")
    blocks.extend(record_text(record) for record in opponents["most_losses"])
    if not opponents["most_losses"]:
        blocks.append("No losses against known opponent colors.")
    blocks.append("**Team — lowest win percentage against**")
    blocks.extend(record_text(record, percentage=True) for record in opponents["worst_percentage"])
    if not opponents["worst_percentage"]:
        blocks.append("No wins or losses against known opponent colors.")
    blocks.append("**Team — top 3 opponent colors by games played**")
    blocks.extend(record_text(record) for record in opponents["popular"])
    if not opponents["popular"]:
        blocks.append("No games against known opponent colors.")
    if opponents["unknown"]:
        blocks.append("Unknown opponent colors — " + record_text(opponents["unknown"]))
    if report["missing"]:
        blocks += ["No completed sync: " + ", ".join(safe(n, 80) for n in report["missing"])]
    pages, pending = [], intro
    for block in blocks:
        # Individual lines are bounded by the finite set of color combinations.
        if len(pending) + len(block) + 1 > 3800:
            pages.append(EmbedSpec("Weekly Duels summary", pending, footer=footer))
            pending = intro
        pending += block + "\n"
    pages.append(EmbedSpec("Weekly Duels summary", pending, footer=footer))
    return tuple(pages)

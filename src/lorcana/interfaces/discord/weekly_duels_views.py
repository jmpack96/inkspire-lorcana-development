"""Bounded weekly report pages, shared by slash command and scheduled delivery."""
from lorcana.duels.weekly import WEEKLY_TIMEZONE
from lorcana.interfaces.discord.matchup_views import safe
from lorcana.interfaces.discord.views import EmbedSpec


def weekly_views(report):
    start, end = (report[k].astimezone(WEEKLY_TIMEZONE) for k in ("start", "end"))
    intro = f"{start:%b %d, %Y %H:%M %Z} → {end:%b %d, %Y %H:%M %Z}\nAll queues, including team games; one count per player/game.\n"
    footer = "Decks grouped by colors, not exact builds. W-L-D; ? = unknown result. Most losses = count, not loss rate. Imported history only."
    blocks = []
    for row in report["rows"]:
        blocks.append(f"**{safe(row['player'], 80)} — {row['games']} games**")
        for deck in row["decks"]:
            blocks.append(f"• {deck['colors']}: {deck['win']}-{deck['loss']}-{deck['draw']}" +
                          (f" · ? {deck['unknown']}" if deck['unknown'] else ""))
        blocks.append("")
    if not blocks:
        blocks = ["No team members have a configured Duels connection."]
    losses = report["opponent_losses"]
    blocks.append("**Team — most losses against**")
    blocks.append(", ".join(losses["colors"]) + f" — {losses['count']} losses each"
                  if losses["colors"] else "No losses against known opponent colors.")
    if losses["unknown"]:
        blocks.append(f"Additional losses against unknown opponent colors: {losses['unknown']}")
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

"""Bounded practice embeds: private facts, denominators, and explicit coverage."""
from collections import defaultdict

from lorcana.duels.practice import colors_label, record
from lorcana.interfaces.discord.views import EmbedField, EmbedSpec


def _safe(value):
    return str(value).replace("`", "'").replace("@", "＠").replace("\n", " ")[:120]


def _rate(values):
    known = [v for v in values if type(v) is bool]
    return f"{sum(known)}/{len(known)} ({100 * sum(known) / len(known):.1f}%)" if known else "n/a (0 evaluable)"


def _groups(rows, key, maximum=12):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    fields = [EmbedField(_safe(label), record(group)) for label, group in ordered[:maximum]]
    if len(ordered) > maximum:
        remaining = [row for _, group in ordered[maximum:] for row in group]
        fields.append(EmbedField(f"Other {len(ordered) - maximum} groups", record(remaining)))
    return tuple(fields)


def _coverage(report):
    status = report["status"]
    sync = status["last_sync"].strftime("%Y-%m-%d %H:%M UTC") if status["last_sync"] else "never"
    text = (f"Last {report['days']} days • ranked: "
            f"{ {True: 'yes', False: 'no', None: 'all'}[report['ranked']] }\n"
            f"{len(report['rows'])} games • {report['evidence_count']} with current parsed replays. "
            f"Latest account sync: {sync}.")
    if report["deck"]:
        text += f"\nDeck filter: `{report['deck']}`. Games without a known deck cannot match."
    if report["profile"] == "ruby_sapphire":
        text += "\nRuby/Sapphire color pair only."
    if report["truncated"]:
        text += "\nLimited to newest 2,000 games BEFORE deck/profile filters; narrow the date range."
    if status["attention"]:
        text += f"\n{status['attention']} account connection(s) inactive or needing authentication."
    if not status["connections"]:
        text += "\nNo Duels account is linked. Ask an administrator to configure Duels sync."
    return text


def summary_views(report):
    rows = report["rows"]
    if not rows:
        return (EmbedSpec("Practice summary", _coverage(report) + "\nNo matching synced games."),)
    fields = [EmbedField("Overall", record(rows))]
    for value, label in ((True, "Went first"), (False, "Went second"), (None, "Starting order unknown")):
        group = [r for r in rows if r["went_first"] is value]
        if group:
            fields.append(EmbedField(label, record(group)))
    fields.append(EmbedField("Deck coverage", f"{sum(r['deck_id'] is not None for r in rows)}/{len(rows)} games have a recorded decklist."))
    footer = "Game records, not match records. Win % = wins / (wins + losses + draws). Small samples are descriptive."
    return (
        EmbedSpec("Practice summary", _coverage(report), tuple(fields), footer),
        EmbedSpec("Practice matchups", "Opponent colors, not confirmed archetypes.",
                  _groups(rows, lambda r: colors_label(r["opponent_deck_colors"])), footer),
        EmbedSpec("Practice deck versions", "Use the 12-character ID as the deck filter. IDs distinguish exact provider card printings.",
                  _groups(rows, lambda r: f"{colors_label(r['your_deck_colors'])} • {r['deck_id'][:12]}" if r["deck_id"] else "Unknown deck"), footer),
        EmbedSpec("Practice queues", "Check the queue mix before comparing performance.",
                  _groups(rows, lambda r: f"{r['queue_name'] or r['mode'] or 'Unknown queue'} • {r['match_format'] or '?'} • ranked={r['ranked']}"), footer),
    )


def opening_views(report):
    all_metrics = report["metrics"]
    metrics = [m for m in all_metrics if m["eligible"]]
    description = _coverage(report)
    description += f"\nInspected {len(all_metrics)} replays; {len(metrics)} have a usable opening timeline."
    if len(metrics) != len(all_metrics):
        description += " Replays with parser warnings or missing opening history are excluded."
    if report["openings_limited"]:
        description += "\nOpening inspection is limited to the newest 100 parsed replays matching the filters."
    counts = [m["mulligan_count"] for m in metrics if m.get("mulligan_count") is not None]
    uninkables = [m["post_uninkables"] for m in metrics if m.get("post_uninkables") is not None]
    fields = [EmbedField("Mulligans", f"Average returned: {sum(counts)/len(counts):.2f} cards (n={len(counts)}).\nFull seven returned: {_rate([c == 7 for c in counts])}" if counts else "No complete mulligan evidence."),
              EmbedField("Post-mulligan hand", "3+ uninkable cards: " + _rate([n >= 3 for n in uninkables]))]
    for number in range(1, 4):
        turns = [t for m in metrics for t in m["turns"] if t["number"] == number and t["complete"]]
        ink = [t["ink"] for t in turns if type(t["ink"]) is int]
        fields.append(EmbedField(f"Your turn {number}",
            f"Completed turns: {len(turns)}. Average ending ink: " +
            (f"{sum(ink)/len(ink):.2f} (n={len(ink)})." if ink else "n/a.") +
            ("\nEnded with 3+ ink: " + _rate([n >= 3 for n in ink]) if number == 2 else "")))
    for order, label in ((True, "Went first"), (False, "Went second")):
        ink = [t["ink"] for m in metrics if m["went_first"] is order for t in m["turns"]
               if t["number"] == 2 and t["complete"] and type(t["ink"]) is int]
        fields.append(EmbedField(f"{label}: 3+ ink at end of own turn 2", _rate([n >= 3 for n in ink])))
    footer = "Missing values are excluded, not treated as failures. Only recorded END_TURN states count as completed turns."
    pages = [EmbedSpec("Practice openings", description, tuple(fields), footer)]
    if report["targets"]:
        turn2 = [(m, next((t for t in m["turns"] if t["number"] == 2 and t["complete"]), None)) for m in metrics]
        turn2 = [(m, t) for m, t in turn2 if t is not None]
        target_fields = [
            EmbedField("Initial seven contained a target", _rate([m.get("initial_target") for m in metrics])),
            EmbedField("Kept a target when initial seven contained one", _rate([m.get("kept_target") for m in metrics if m.get("initial_target") is True])),
            EmbedField("Post-mulligan hand contained a target", _rate([m.get("post_target") for m in metrics])),
            EmbedField("Target seen in hand during own turn 2", _rate([t.get("target_seen") for _, t in turn2])),
            EmbedField("Target played during own turn 2", _rate([t.get("target_played") for _, t in turn2])),
            EmbedField("Played on own turn 2 when seen that turn", _rate([t.get("target_played") for _, t in turn2 if t.get("target_seen") is True])),
        ]
        candidates = [(m, t) for m, t in turn2 if t.get("target_seen") is True and t.get("target_played") is False]
        if candidates:
            target_fields.append(EmbedField(f"Review candidates ({len(candidates)}; newest 5 shown)", "\n".join(
                f"`{m['game_id']}` • own T2, end seq {t['end_seq']}" for m, t in candidates[:5])))
        pages.append(EmbedSpec("Opening card targets", ", ".join(_safe(t) for t in report["targets"]) +
            "\nSeen means observed in hand, not necessarily playable. Plays do not prove ability resolution. "
            "Review candidates are observations, not mistakes.", tuple(target_fields), footer))
    return tuple(pages)

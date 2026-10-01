# Team Duels summary

`/duels-summary` posts the configured active team's current-set summary publicly
in the invoking server channel. The caller must be a linked active team member.
Errors remain private. No AI key, migration, or replay re-import is required.
Bot startup registers the command automatically after deployment.

One row per active member with a configured, non-inactive Duels connection shows:

- **Main**: their most-played known deck colors, using the team's circle emojis.
  Ties are labeled and every tied combination is listed below the table.
- **Played**: top color game count / games with known colors. Unknown colors do
  not compete for the most-played spot.
- **Avg mull**: mean number of cards mulliganed per game with validated evidence,
  displayed to two decimal places. Confirmed zero-card mulligans count as zero.
- **Sample**: valid mulligan evidence count / all imported games in the period.
  Missing, malformed, warned, or inconsistent openings are excluded from the
  average, rather than counted as zero. An unavailable average displays a dash.

The current set uses the same catalog release-date rule as matchup reports.
History includes all queues and team-versus-team games: this report describes
individual play habits, not external matchup results. Games missing a start
date cannot be placed in the period. History without replays still counts for
colors and game totals. Members without games remain visible.

Multiple accounts belonging to one member/game are deduplicated using the latest
observation. Only the latest valid normalization from the current parser for that
exact account/game perspective supplies evidence. The query streams compact
opening data in batches with no arbitrary sample cap; full actions are not
loaded. Only aggregates are displayed, not private hands or replay details.

The command shows up to twenty members per page with existing Previous/Next
buttons, splitting earlier if Discord limits require it.
Color combinations represent colors, not exact deck builds. Sync coverage means
members who have ever completed sync, not a guarantee of complete current-set
history. Future modules can add play/draw splits, deck-specific mulligan averages,
and recent activity without changing the slash-command name.

Apply `duels-team-summary.patch` after the combined team-table and emoji patches,
then deploy/restart the bot normally.

A configured connection has a nonempty `env:` credential reference in PostgreSQL.
The bot does not inspect worker secrets or verify token validity. Connections with
authentication errors remain visible for troubleshooting; inactive connections
are hidden. Active linked teammates without Duels connections may still view
team reports.

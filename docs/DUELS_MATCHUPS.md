# Current-set matchup commands

This update replaces the public `/practice` group with two simpler commands.
It applies **after** `duels-practice-tools.patch`. No migration, replay import,
new package, AI key, or AI analyzer is required.

## Use in Discord

- `/player-matchups`: your current-set results.
- `/player-matchups player:`: select a teammate from the autocomplete list.
- `/team-matchups`: combined matchup records across the active team.
- Either command: optionally select `opponent_colors`, such as Emerald/Steel.

The player option uses the internal active roster, so players do not need a
Play Hub rating or a published Elo run to appear. Omit it for yourself. Do not
enter a name without choosing the matching autocomplete result.

Each row shows played deck colors against opponent colors, W/L/D,
win percentage, game count, and queue/format/ranked status. Team reports use
compact monospace tables grouped by queue, with up to twelve rows per page.
Team records pool all active members by played deck and opponent colors within
each queue. Columns are Deck, Vs, W-L-D, Win%, and N (all games, including unknown
outcomes). A separate `?` count appears when a table contains unknown outcomes.
Played and opposing colors use paired circle emojis (for example, 🔴🔵 for
Ruby/Sapphire). Unknown colors use ❓. No color legend is included.
Use `/player-matchups` for individual player results.
Exact queue records stay separate, even when their displayed labels match.
Most-played matchups appear first within each queue; queues follow their first
appearance in the most-played results. Player reports retain six rows per page.
Use Next/Previous in the same message. Player reports are private; team reports
are public in the invoking channel. Unknown outcomes are shown separately and excluded from win
percentage. Draws are included in the win-percentage denominator.

## Set period

The latest imported catalog's `metadata_json.sets` supplies expansion names and
release dates. The most recently released numeric expansion defines the start
of the period, inclusive, through now. Future expansions and nonnumeric promo
sets are excluded. Date-only releases start at 00:00 UTC. This is the provider's
catalog release date, not a guessed Duels early-access date or ladder season.
Old cards played during the current set period are included.

The report displays the set, start date, and catalog update date. Keep the
catalog refreshed as new sets release; a stale catalog cannot know an unlisted
set. To refresh (enqueue once, then let the worker finish):

```bash
lorcana catalog-enqueue-refresh
```

If no usable release date exists, the command gives this instruction instead
of silently falling back to a rolling time window. Games without `started_at`
cannot be placed in a set period and are excluded.

## Scope, separation, and privacy

Only linked Discord users who are active members of the configured active team
may use reports or roster autocomplete. Selected players must also be active
members of that team. This revision provides teammate access to aggregate
results as requested; it does not expose private hands, replays, or credentials.
Player reports and error responses remain ephemeral. Successful team reports are visible to everyone in the invoking channel. No individual opt-in table is introduced.

Own/opponent colors are kept separate. Exact queue ID/name, mode, match format,
and ranked flag remain separate grouping dimensions. Recognized Core and
Infinity queue labels are labeled accordingly; unidentified queues are marked
Format unknown and never silently assigned a format. Colors are not confirmed
archetypes, and wins are descriptive rather than a causal measure of skill.

Repeated accounts for one member/game count once using the latest observation.
Games observed for two active teammates are excluded from external matchup
results for both player and team views. The exclusion count is player-results,
not unique games. An internal game cannot be identified this way if only one
side has been synced. No arbitrary history cap is applied: PostgreSQL groups
history-only data before returning it. Replays are not required.

A coverage line indicates how many selected members have ever completed sync;
it does not promise their entire current-set history is up to date. Missing
sync players are named. Existing Duels sync schedules continue unchanged.

## Apply

From the repository root with the earlier patch already applied:

```bash
git apply --check /path/to/duels-current-set-matchups.patch
git apply /path/to/duels-current-set-matchups.patch
```

Deploy/restart the bot normally. Its startup command sync removes `/practice`
and registers `/player-matchups` and `/team-matchups`. Legacy practice code stays
in the repository but is no longer exposed through slash commands.

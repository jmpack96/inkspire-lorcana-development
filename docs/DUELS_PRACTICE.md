# Private Duels practice reports (no AI)

> Superseded Discord interface: see `DUELS_MATCHUPS.md` for the current
> `/player-matchups` and `/team-matchups` commands. Legacy internals remain for reuse.

`/practice summary` and `/practice openings` read existing synced Duels data.
They make no Duels API or model calls and do not enqueue Coach analysis. The
practice service is wired independently of `LORCANA_COACH_ANALYZER`. Leave that
variable unset if AI coaching should remain disabled.

## Deploy and use

Apply the patch from the repository root, using the actual downloaded path:

```bash
git apply --check /path/to/duels-practice-tools.patch
git apply /path/to/duels-practice-tools.patch
```

Deploy the updated bot through your normal workflow. This change requires no
schema migration, new dependency, or replay reimport. The existing bot startup
sync registers the `practice` command group. Existing Discord/member links and
Duels account sync are prerequisites; see `OPERATIONS.md` for account setup.

Examples (select options through Discord's slash command UI):

- `/practice summary days:30 ranked:true`
- `/practice summary days:90 deck:<12-character ID from the summary>`
- `/practice openings days:30`
- `/practice openings days:90 profile:Ruby/Sapphire: Tipo and Sail`
- `/practice openings cards:Grandmother Willow - Ancient Advisor`

The Ruby/Sapphire profile restricts history to that color pair and tracks Tipo -
Growing Son and Sail the Azurite Sea. The `cards` option overrides card targets,
not the profile's color restriction. It accepts up to eight comma-separated full
names or exact Duels card IDs. Matching ignores case, repeated whitespace and
dash style, but does not guess partial names or resolve alternate printing IDs.
Use full card names when you want to match different printings of the same card.

Every response is ephemeral. There is no player/member selector: the linked
member is resolved from the invoking Discord user. Raw hands and opponent names
are not shown in these reports. Results are paginated in one private message.

## Summary definitions

- Records count games, not best-of-three matches. Wins divided by wins + losses
  + draws is the displayed win percentage. Unknown outcomes are shown and excluded
  from that denominator. Unknown starting order has its own group.
- Opponent colors are not confirmed archetypes. Queue, format and ranked-status
  groups help reveal mixed practice conditions. Omitted `ranked` includes all;
  `false` excludes unknown ranked status, just as `true` does.
- Deck IDs hash the sorted multiset of recorded provider card IDs and quantities.
  Deck order does not matter; card printing IDs do. They identify recorded lists,
  not a claim about deck legality or completeness. Missing/unsupported decklists
  remain unknown. A deck filter cannot include games without a known deck.
- Each game appears once per member even when multiple linked accounts observed
  it. The latest observation selects the account perspective; the latest valid
  normalization for that account/game and current parser version supplies replay
  evidence. An older valid normalization may be used if a newer revision is invalid.
- Games without replays still count in summary results. Replay coverage is separate.
- Reports use UTC instants for a rolling 1–365-day range based on `started_at`.
  Games without a start timestamp are excluded. Latest account sync is shown;
  this is not a guarantee that every linked account is equally fresh.

## Opening definitions

Metrics are computed from existing normalized replays, without changing the
legacy Coach feature extractor or its versioned evidence. On-demand calculation
avoids a database migration and backfill for the first release.

- Own turn numbers count active-player segments starting at the recorded game
  start, rather than reusing Duels' turn labels. The second player's first turn
  can carry Duels label 2. Decisions during an opponent's turn do not enter own-turn
  metrics. Undone actions and undo control frames do not count as decisions.
- Opening timelines with parser warnings, missing initial history, or known
  multiplayer games are excluded. Missing mulligan fields or inconsistent hands
  make mulligan metrics unknown, not zero. Each metric displays its own denominator.
- Only turns with a recorded `end_turn` count as completed. Games ending mid-turn
  (including a winning turn) are excluded from that turn's completion statistics.
- Ending ink uses the state immediately before the recorded end-turn action.
  Having 3+ ink at the end of own turn 2 is an observed resource milestone, not
  proof a named card's effect resolved. It is shown separately for first/second.
- Card targets measure initial-hand presence, whether a target was kept when
  initially present, post-mulligan presence, presence during own turn 2, and plays
  during that turn. "Seen" does not establish legality, affordability, or quality
  of a play. Unknown card identities cannot establish absence.
- Review candidates are completed second turns with a target observed but no
  target play. IDs and end-action sequence numbers locate the evidence; these
  are not automatic misplay verdicts. The newest five candidates are shown.
- Post-mulligan 3+ uninkable-card frequency is descriptive, not a mulligan grade.

## Bounds and interpretation

Summary queries read at most the newest 2,000 games in the date/ranked scope,
then apply deck/profile filters. A visible warning asks users to narrow dates
when capped. Openings inspect at most the newest 100 parsed replays in the
filtered sample; coverage and limits are displayed. Large breakdowns show the
12 largest groups and combine the remainder under an explicitly labeled group.

Do not treat changes in win rates as proof of improvement or a card's causal
impact. Samples can differ in opponents, queue, date, or deck. Team aggregates,
manual deck labels, deck comparison experiments, and resolved card-specific ramp
rules are future work rather than implied capabilities of this release.

## Validation

```bash
python -m pytest tests/unit/duels tests/unit/discord -q
# Use ONLY a dedicated disposable PostgreSQL test database:
TEST_DATABASE_URL=postgresql://.../lorcana_test python -m pytest tests/integration/db/test_practice_queries.py -q
```

The integration fixture performs destructive schema resets on its test database.
Never point `TEST_DATABASE_URL` at production.

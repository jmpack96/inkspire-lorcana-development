# Phase 4 — Ratings rewrite and publication

The ratings domain no longer defines eligibility through an implicit SQL `WHERE` clause or treats the numerically latest run as live.

## Policies

- `legacy_parity_v1` preserves the historical eligible population for migration verification.
- `global_elo_v1` adds explicit supported-format and `event_sync_state = complete` requirements.

On the frozen source `lorcana-pre-parser-fix-20260913T205901Z.db` (SHA-256 `cac0950afc84844fcb8367e00f93e4fe2f5b31f5a51fc2458aba02775a619069`):

| Policy | Inputs | Players | Ordered input digest | Final state digest |
| --- | ---: | ---: | --- | --- |
| `legacy_parity_v1` | 477,438 | 48,035 | `f02339fbd385b250af996885fc816707c1aa977620f12bb4dc565447565b3ecf` | `0e7412859e42b67fe089e9a9f6c41b92d8c51e054524d96f9bd5634dcad4e846` |
| `global_elo_v1` | 477,334 | 48,033 | `90b3f2ff2f0138b997c57fb806bd0b164d8596997424dbcfcd45b4e1120664de` | `acea970f022dc669090c750b714b0725b230a545ce9b1c0a5781b1be74dc5a4f` |

The 104-match difference is intentional: those matches belong to events whose migrated sync state is `partial`. No otherwise-eligible historical matches were rejected by the format gate.

The full frozen legacy arithmetic oracle processed 477,438 matches and produced 954,876 history rows with zero invalid matches. Its final-state digest is exactly the same as the new Elo calculator's legacy-parity result.

Machine-readable regression values live in `tests/oracles/frozen_rating_baseline.json`.

## Build semantics

A rating build:

1. Creates a `building` run with algorithm, algorithm version, policy version, and parameters.
2. Streams deterministic Play Hub candidates through the selected pure policy.
3. Writes an ordered immutable `rating_run_inputs` snapshot containing the player/result facts and ordering facts used by Elo.
4. Calculates only from that snapshot.
5. Writes history/current results in one transaction and validates counts and numerical invariants.
6. Marks the run `validated`.
7. Changes a publication pointer only in a later explicit transaction.

A failed build never changes `rating_publications`.

## Operational commands

```bash
lorcana ratings-build --policy legacy
lorcana ratings-build --policy global --publish --publication-name global_elo
lorcana ratings-publish <RUN_UUID> --publication-name global_elo
lorcana ratings-leaderboard --publication-name global_elo --limit 25
```

Consumers resolve a named publication once and then use that immutable run ID for the rest of the response.

## Bounded run retention

Rating storage is intentionally bounded. Each publication retains only two complete generations:

1. `rating_run_id`: the current published run.
2. `previous_rating_run_id`: the immediately preceding published run.

Publishing a new run rotates the old current run into the previous slot and prunes every older completed run and its `rating_run_inputs`, `rating_history`, and `rating_current` rows in the same transaction. A run that is actively `building` is never pruned. This prevents scheduled Elo rebuilds from growing the database without bound while preserving one rollback/comparison generation.

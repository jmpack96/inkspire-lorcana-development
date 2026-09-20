# Operations

This document is the supported operator path for the Lorcana platform. Normal operation should not require hand-written SQL.

## Process model

Run exactly two application processes against one PostgreSQL database:

- `lorcana-worker` owns schedules, Play Hub ingestion, Elo builds/publication, Duels synchronization, catalog refreshes, and Coach analysis jobs.
- `lorcana-bot` owns only the Discord gateway and command presentation.

The bot must never be used as a scheduler.

## Live team-event Discord links

Set `LORCANA_LIVE_EVENT_CHANNEL_ID` to the destination Discord channel ID on
both the worker and bot services, then rerun `lorcana schedules-bootstrap`.
The worker refreshes possible team events every five minutes and queues a link
only when all of these checks pass:

- an active team member has a freshly synced active registration;
- Play Hub freshly reports an exact `LIVE` status;
- the current instant is between the event start and end times;
- the event start date is today in the event's declared timezone;
- the event has a valid Play Hub URL; and
- that event has not already been queued for the configured channel.

The bot delivers the durable queue and retries transient Discord failures. The
message contains only the Play Hub event URL. Leave the variable unset on both
services to disable the feature.

## First-time database setup

Apply the schema before starting either runtime process:

```bash
alembic upgrade head
lorcana db-check
```

For the historical cutover, transfer the frozen SQLite database once and validate the result before enabling live jobs:

```bash
lorcana sqlite-preflight --source /path/to/frozen.db
lorcana sqlite-transfer --source /path/to/frozen.db
lorcana sqlite-validate --source /path/to/frozen.db
```

The transfer refuses a non-empty target rather than merging ambiguously with live data.

## Bootstrap identities and teams

Load the team bootstrap data:

```bash
lorcana teams-bootstrap --file data/bootstrap/inkspire.json
```

Link a Discord account to the internal member who owns a known Play Hub identity:

```bash
lorcana identity-link-discord --playhub-player-id 7504 --discord-user-id 123456789012345678
```

## Bootstrap recurring platform work

Configure the shared recurring schedules idempotently:

```bash
lorcana schedules-bootstrap
```

The defaults are:

| Schedule | Cadence | Purpose |
| --- | --- | --- |
| `playhub-discover-upcoming` | daily 02:00 UTC | discover events starting today through the next 30 days |
| `playhub-import-sweep` | every 2 hours | queue imports/retries for recent events that have started and are not complete |
| `maintenance-prune-jobs` | daily 06:30 UTC | delete terminal worker jobs/attempts older than 30 days in bounded batches |
| `catalog-lorcast-daily` | daily 07:00 UTC | refresh the versioned card catalog snapshot |
| `ratings-global-daily` | daily 08:00 UTC | build, validate, and publish `global_elo` |

The Elo publication workflow retains only the current published run and its immediately previous published run. Older completed rating runs and their dependent history/input rows are pruned during publication. Failed transient builds are pruned immediately, and scheduled refreshes first compare the source digest so an unchanged dataset does not write a duplicate run. Recurring builds must not become an unbounded Elo archive.

The worker materializes due schedules into the durable `jobs` queue. Re-running `schedules-bootstrap` updates the named schedules rather than creating duplicates.

## Duels setup

Create one connection for a member. The token itself belongs in an environment variable; PostgreSQL stores only the environment-variable reference.

```bash
lorcana duels-create-connection \
  --playhub-player-id 7504 \
  --credential-env DUELS_TOKEN_JACOB \
  --label Jacob
```

Queue the first sync using the returned connection UUID:

```bash
lorcana duels-enqueue-sync <connection-uuid>
```

Then configure recurring sync for that connection:

```bash
lorcana duels-schedule-sync <connection-uuid> --hours 6
```

Each connection has its own schedule and access boundary. There is deliberately no global Duels schedule.

## Coach setup

Coach requires a catalog snapshot and an enabled analyzer. Queue an initial catalog refresh after a fresh install rather than waiting for the first scheduled run:

```bash
lorcana catalog-enqueue-refresh --generation initial
```

For the OpenAI analyzer, configure:

```text
LORCANA_COACH_ANALYZER=openai
OPENAI_API_KEY=<secret>
OPENAI_COACH_MODEL=<supported model>
```

Coach inputs are pinned to replay normalization, deterministic feature-set, catalog, analyzer, and prompt versions. Model output is stored as a structured analysis/report; the model is not treated as the source of replay facts.

## Elo operations

A manual production build can be run with:

```bash
lorcana ratings-refresh --publication-name global_elo --published-by operator
```

Legacy parity is kept as a test/oracle policy, not as a production CLI workflow.

Publishing a validated run rotates `current -> previous` and prunes older completed runs in the same transaction. Do not add a second cleanup scheduler for Elo retention.

## Failure handling

Jobs are leased and retried durably. A worker crash does not imply that the job failed permanently: expired leases are reclaimable until `max_attempts` is reached. Permanent malformed-job errors are not retried.

Play Hub source facts, raw Duels replay revisions, rating snapshots, and Coach evidence are persisted separately from workflow state. A retry should resume workflow rather than rewrite historical evidence in place.

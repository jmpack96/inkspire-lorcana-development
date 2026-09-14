# Project status — platform v3 release candidate

Date: 2026-09-13

## Core architecture status

The ground-up rearchitecture is complete for the three required product surfaces:

- Global Elo
- Discord bot
- Duels-backed Coach

All three are consumers of one PostgreSQL-backed modular monolith and shared application services.

## Implemented

### PostgreSQL and migrations

- PostgreSQL is the only live application database.
- Alembic owns schema creation/evolution.
- The legacy SQLite database is supported only as a frozen, read-only source for one-time migration.
- SQLite transfer performs transformation preflight, source SHA-256 verification, row/digest validation, and foreign-key validation.

### Play Hub

- HTTP client, pure parsers, repository, import service, discovery service, and query service are separated.
- Event discovery is durable and windowed.
- Recent started events are swept into idempotent import jobs.
- Complete, partial, no-results, and failed import states are explicit.
- Import attempts are append-only operational history; event source facts are separate from sync state.

### Elo

- Pure Elo math is separated from eligibility policy and persistence.
- `global_elo_v1` excludes partially imported events.
- `legacy_parity_v1` exists only for regression verification.
- Every published run snapshots the exact ordered calculation facts and a deterministic input digest.
- Scheduled refreshes preview the source digest and do not create a run when eligible source data is unchanged.
- Publication is atomic.
- **Retention is hard-bounded to current + previous published runs.**
- Older completed runs are pruned during publication.
- Failed transient builds are pruned immediately.
- The frozen historical oracle and new calculator produced the same legacy final-state digest.

### Identity and teams

- Members, teams, team membership, Play Hub links, and Discord account links are database data.
- The Inkspire mapping is bootstrap data, not Python configuration.
- Provider identities remain distinct from internal member identity.

### Durable jobs

- PostgreSQL-backed queue with leases, fenced completion, retries, idempotency keys, and recurring schedules.
- Scheduling runs only in the worker, never in Discord.
- Shared schedules cover discovery, import sweeping, catalog refresh, Elo refresh, and operational job pruning.
- Duels recurring sync is configured per connection.
- Terminal job/attempt history older than 30 days is pruned in bounded batches.

### Duels

- Member-owned connections use environment-variable credential references; bearer tokens are not stored in PostgreSQL.
- History sync is resumable and connection-scoped.
- Raw replay bytes are immutable, SHA-256-deduplicated revisions.
- Changed provider replay bytes create a new revision rather than overwriting evidence.
- Replay normalizations and deterministic feature sets are separately versioned.
- Access to private replay evidence is checked through the owning member/connection.

### Catalog and Coach

- Lorcast catalog ingestion creates immutable, content-hashed snapshots and avoids duplicate snapshots when unchanged.
- Coach inputs are pinned to normalization, feature-set, catalog, optional decklist, analyzer, and analyzer/prompt generation.
- Effective replay actions exclude undone actions from normal-line evidence.
- Analyzer output is validated against allowed action IDs.
- Findings and rendered report are persisted; viewing a report does not call the model again.
- Discord Coach requests/reports are private/ephemeral.

### Discord

- Thin gateway adapter over application/query services.
- No SQL, Play Hub HTTP, rating calculation, or scheduler ownership.
- Current command surfaces include player profile, global leaderboard, team leaderboard, database status, Set Championship lookup, Coach request, and Coach report.

### Operations/deployment

- Installable Python package and CLI.
- Dockerfile shared by worker and bot services.
- GitHub Actions includes a disposable PostgreSQL service and runs the full suite plus Alembic upgrade/downgrade/upgrade before deployment.
- Railway deployment is worker-first (migrations), then bot.
- Supported setup commands exist for teams, Discord identity links, Duels connections/schedules, recurring platform schedules, catalog refresh, Elo refresh, and migration validation.

## Frozen historical regression facts

Frozen SQLite SHA-256:

`cac0950afc84844fcb8367e00f93e4fe2f5b31f5a51fc2458aba02775a619069`

Corpus:

- 515,646 Play Hub matches
- 175,556 registrations
- 165,011 events
- 48,974 players

Elo regression:

- `legacy_parity_v1`: 477,438 matches / 48,035 players / zero calculator rejects
- `global_elo_v1`: 477,334 matches / 48,033 players
- exact policy difference: 104 matches from partially imported events
- legacy final-state digest: `0e7412859e42b67fe089e9a9f6c41b92d8c51e054524d96f9bd5634dcad4e846`

## Current automated validation

Local environment:

- all unit/parser tests pass
- PostgreSQL integration tests are collected but skipped when `TEST_DATABASE_URL` is absent
- Alembic full upgrade SQL renders successfully offline
- Alembic full downgrade SQL renders successfully offline
- wheel builds and imports outside the repository using the installed local build toolchain

The GitHub Actions workflow is designed to turn the skipped integration tests into mandatory live-PostgreSQL tests.

## Remaining gate before production cutover

The only core gate that cannot be executed in the current ChatGPT container is a full run against a disposable live PostgreSQL server. Docker/PostgreSQL server binaries are not available here.

The first GitHub Actions workflow run should therefore be treated as a release gate. Do not migrate the production historical database or enable Railway schedules unless that pipeline passes all integration tests and the Alembic round-trip.

## Deliberately deferred

These are extensions, not blockers for Elo/Discord/Coach:

- HTTP API / direct ChatGPT integration
- intentional-draw tournament tool
- team trend dashboards
- broader live tournament tooling

They belong to Phase 9 and can build on the current services without reopening the core architecture.

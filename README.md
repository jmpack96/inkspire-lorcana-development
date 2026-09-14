# Lorcana Platform

A PostgreSQL-backed modular monolith for Lorcana tournament ingestion, global Elo, Discord tools, Duels replay ingestion, and evidence-based coaching.

The project is intentionally split by responsibility rather than into microservices. `lorcana-worker` and `lorcana-bot` run the same application package against the same PostgreSQL database.

## Core guarantees

- PostgreSQL is the live system of record; Alembic is the only schema migration path.
- Play Hub HTTP, parsing, workflow, and SQL are separate layers.
- Elo runs snapshot the exact ordered match facts used for calculation.
- **Only the current and immediately previous published Elo runs are retained.** Older completed runs are pruned automatically during publication.
- Discord is a thin interface: no SQL, ingestion, Elo calculation, or scheduling in command handlers.
- Background work uses durable PostgreSQL jobs with leases, retry limits, and idempotency keys.
- Duels raw replay bytes are immutable revisions; normalizations and feature sets are separately versioned.
- Coach reasons from verified replay/catalog evidence and persists structured findings tied to action IDs.
- Provider credentials are referenced from environment variables and are not stored as plaintext in PostgreSQL.

See [`docs/LORCANA_REARCHITECTURE.md`](docs/LORCANA_REARCHITECTURE.md) for the architecture contract and [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for supported administration.

## Local development

Python 3.11+ is supported; CI and the deployment image currently use Python 3.13.

```bash
python -m pip install -e '.[dev,bot]'
cp .env.example .env
pytest -q
```

Set a PostgreSQL `DATABASE_URL`, then:

```bash
alembic upgrade head
lorcana db-check
```

Integration tests require a disposable PostgreSQL database via `TEST_DATABASE_URL`. The integration fixture refuses destructive setup unless the database name clearly identifies it as a test database (or the explicit test override is configured).

## Runtime commands

```bash
lorcana-worker   # schedules + durable background jobs
lorcana-bot      # Discord gateway only
```

Common administration:

```bash
lorcana schedules-bootstrap
lorcana teams-bootstrap --file data/bootstrap/inkspire.json
lorcana ratings-leaderboard --limit 25
lorcana --help
```

## Historical cutover

The one-time SQLite migration is deliberately read-only on the source and refuses an ambiguous non-empty PostgreSQL target:

```bash
lorcana sqlite-preflight --source /path/to/lorcana.db
lorcana sqlite-transfer --source /path/to/lorcana.db
lorcana sqlite-validate --source /path/to/lorcana.db
```

The frozen regression corpus used during the rearchitecture contained 515,646 matches and the new legacy-parity Elo path reproduced the old calculator's final-state digest exactly. The production `global_elo_v1` policy intentionally excludes matches from partially imported events.

## Deployment

The included Dockerfile supports both runtime services. For the planned GitHub → Railway deployment, see [`docs/DEPLOYMENT_RAILWAY.md`](docs/DEPLOYMENT_RAILWAY.md). The included GitHub Actions workflow tests against PostgreSQL before deploying the worker and then the bot.

# Phase 1 implementation checkpoint

## Starting point

This working tree was created from clean committed `main` at commit `8f03946` (`fixed parse bug`). The uploaded uncommitted restructure was left untouched and used only as a source for proven pure Elo/replay parsing behavior and regression fixtures.

## Implemented

- Installable `src/lorcana` package configured by `pyproject.toml`.
- PostgreSQL-only runtime configuration (`DATABASE_URL`).
- SQLAlchemy 2 engine and explicit transaction helper.
- Alembic as the only schema-creation/migration path.
- Initial `playhub_*` source/ingestion-state schema.
- Initial immutable `rating_*` run/input/history/current/publication schema.
- `rating_history.result` is checked text (`WIN`/`LOSS`/`DRAW`), fixing the legacy SQLite type mismatch.
- Thin administrative CLI with `lorcana db-check`.
- A concrete PostgreSQL `PlayHubPlayerRepository` to establish the repository/transaction pattern.
- Pure Elo core and its parity-oriented unit tests rescued from the checkpoint.
- Duels replay parser and its two regression fixtures/tests rescued from the checkpoint.
- Guarded PostgreSQL integration tests for migrations and repository behavior.
- Future domain/interface package boundaries are present but intentionally empty.

## Validation performed

- `pytest`: 16 passed, 2 integration tests skipped because `TEST_DATABASE_URL` is not configured, plus 2 replay subtests passed.
- `python -m compileall` succeeds for source, migrations, and tests.
- `alembic upgrade head --sql` successfully renders the initial PostgreSQL migration.
- Every expected Phase 1 table appears in the rendered migration.
- A wheel was built, installed outside the repository tree, and its CLI help/version executed successfully.
- Runtime source contains no SQLite usage and no `metadata.create_all()` schema creation.
- Frozen SQLite source compatibility audit found:
  - 515,646 matches
  - 175,556 registrations
  - 48,974 players
  - 0 duplicate `(event_id, player_id)` registrations
  - 0 checked orphan source foreign keys
  - 0 invalid 0/1 values in the legacy boolean fields checked

## Intentionally not done

- No Play Hub network/import workflow rewrite.
- No SQLite-to-PostgreSQL transfer utility.
- No rating policy/build/publication service.
- No Discord rewrite.
- No durable job worker.
- No identity/team persistence.
- No Duels durable sync/storage pipeline.
- No Coach implementation.
- No Railway changes.
- No production database changes.

## Remaining Phase 1 live-database gate

The migration and repository integration tests still need to be executed against a **dedicated disposable PostgreSQL test database**. The test harness reads `TEST_DATABASE_URL` and refuses destructive migration setup unless the database name contains `test`, unless an explicit override is provided.

Run from the repository root:

```bash
TEST_DATABASE_URL='postgresql://.../lorcana_test' pytest -q tests/integration
```

Do not point this at the production Railway database.

## Next phase

Phase 2 should be a read-only SQLite -> fresh PostgreSQL transfer utility with row-count, key-field, timestamp/type, foreign-key, and checksum validation. Do not dual-write SQLite and PostgreSQL.

# Railway deployment from GitHub

The GitHub repository is the source of truth. Railway runs PostgreSQL plus two application services built from the same repository/Dockerfile.

## Railway topology

Create these services in one Railway project/environment:

1. PostgreSQL
2. `lorcana-worker`
3. `lorcana-bot`

Both application services use the repository `Dockerfile`.

Configure `lorcana-worker`:

- Start Command: `lorcana-worker`
- Pre-Deploy Command: `alembic upgrade head`
- `DATABASE_URL`: reference the Railway PostgreSQL service's `DATABASE_URL`
- any Duels credential environment variables used by configured connections
- Coach variables if Coach is enabled

Configure `lorcana-bot`:

- Start Command: `lorcana-bot`
- `DATABASE_URL`: the same PostgreSQL service reference
- `DISCORD_BOT_TOKEN`
- `LORCANA_DISCORD_TEAM_SLUG`
- Coach configuration if Coach commands should be enabled

Do not expose PostgreSQL publicly just for these application services; services in the same Railway project should use Railway's private database reference.

## GitHub Actions release gate

The included `.github/workflows/ci.yml` runs on pull requests and pushes to `main`.

The verification job starts an ephemeral PostgreSQL 16 service and then runs:

1. the complete pytest suite, including PostgreSQL integration tests;
2. Python bytecode compilation;
3. `alembic upgrade head`;
4. `alembic downgrade base`;
5. `alembic upgrade head` again.

A push to `main` deploys only after verification succeeds. Deployment is ordered:

1. worker;
2. bot.

The worker must retain the Railway **Pre-Deploy Command** `alembic upgrade head`, so schema migration completes as part of the worker deployment before the bot deployment begins.

## GitHub repository secrets

Create these GitHub Actions secrets under **Settings → Secrets and variables → Actions**:

- `RAILWAY_TOKEN` — Railway project token scoped to the target environment
- `RAILWAY_PROJECT_ID`
- `RAILWAY_ENVIRONMENT` — normally `production`
- `RAILWAY_WORKER_SERVICE` — worker service name or ID
- `RAILWAY_BOT_SERVICE` — bot service name or ID

The workflow uses Railway CLI `railway up --ci` and explicitly targets the project, environment, and service. Railway documents project tokens as suitable for automated CI/CD deployments and supports targeting a service/environment/project from the CLI.

For additional protection, configure the GitHub `production` Environment with required reviewers if you want deployments to pause for approval after tests pass.

## Initial production cutover

Do not enable recurring schedules until the historical transfer and validation are complete.

Recommended order:

1. Create the new GitHub repository and push this code to `main`.
2. Provision Railway PostgreSQL plus worker and bot services.
3. Add the GitHub Actions secrets listed above.
4. Configure the worker's pre-deploy command and both services' start commands/environment variables.
5. Let the first GitHub Actions verification pass against its disposable PostgreSQL instance.
6. Deploy the worker so `alembic upgrade head` creates the production schema.
7. Run the frozen SQLite preflight/transfer/validation against production PostgreSQL through a controlled operator session.
8. Load the team bootstrap.
9. Link Discord identities and create Duels connections.
10. Run `lorcana schedules-bootstrap`.
11. Queue one initial catalog refresh and initial Duels syncs.
12. Build/publish the first `global_elo` run and verify `lorcana ratings-leaderboard`.
13. Start/deploy the Discord bot.

Do not point the new worker at the old SQLite database and do not run the legacy scheduled updater alongside the new worker.

## Elo storage reminder

Production Elo retention is intentionally bounded. Publication retains only:

- the currently published Elo run; and
- the immediately previous published Elo run.

Older completed runs are automatically pruned. Failed transient builds are also cleaned up rather than retained indefinitely.

## Rollback principle

Application rollback and data rollback are separate concerns. Railway can redeploy an earlier application build, but Alembic downgrades in production should be deliberate rather than automatic. After production data exists, prefer forward-compatible migrations and corrective forward migrations.

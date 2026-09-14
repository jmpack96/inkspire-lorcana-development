"""Administrative CLI for platform operations and controlled migrations."""

from __future__ import annotations

import argparse
from pathlib import Path
from datetime import date, datetime, timezone
import re
from uuid import UUID, uuid4

from sqlalchemy import text

from lorcana import __version__
from lorcana.bootstrap import ApplicationResources
from lorcana.config import ConfigurationError
from lorcana.db.transfer_sqlite import (
    SQLiteTransferError,
    preflight_sqlite_source,
    transfer_sqlite_to_postgres,
    validate_sqlite_transfer,
)
from lorcana.duels.service import DuelsService
from lorcana.identity.service import IdentityAdminError, IdentityAdminService
from lorcana.jobs.bootstrap import bootstrap_platform_schedules, upsert_duels_sync_schedule
from lorcana.jobs.kinds import enqueue_catalog_refresh, enqueue_duels_sync
from lorcana.jobs.service import JobQueue
from lorcana.playhub.client import PlayHubClient
from lorcana.playhub.service import PlayHubDiscoveryService, PlayHubImportService
from lorcana.ratings.query_service import RatingQueryService
from lorcana.ratings.service import RatingService
from lorcana.teams.service import TeamAdminService, load_team_bootstrap


def _db_check() -> int:
    resources = ApplicationResources.from_env()
    try:
        with resources.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        resources.close()
    print("PostgreSQL connection OK")
    return 0


def _print_report(report) -> None:
    print(f"Source: {report.source_path}")
    print(f"SHA-256: {report.source_sha256}")
    for table in report.tables:
        status = "OK" if table.valid else "MISMATCH"
        print(f"{status:8} {table.table:28} {table.target_rows:>10,} rows  {table.target_digest}")
    if report.foreign_key_violations:
        for violation in report.foreign_key_violations:
            print(f"FK ERROR {violation}")
    else:
        print("Foreign keys: OK")


def _sqlite_preflight(source: Path) -> int:
    digest, counts = preflight_sqlite_source(source)
    print(f"SQLite source: {source.resolve()}")
    print(f"SHA-256: {digest}")
    for table, count in counts.items():
        print(f"OK       {table:28} {count:>10,} transformed rows")
    print("Source preflight: OK")
    return 0


def _sqlite_transfer(source: Path, batch_size: int) -> int:
    resources = ApplicationResources.from_env()
    try:
        report = transfer_sqlite_to_postgres(source, resources.engine, batch_size=batch_size, progress=print)
    finally:
        resources.close()
    _print_report(report)
    print("SQLite -> PostgreSQL transfer committed successfully")
    return 0


def _sqlite_validate(source: Path) -> int:
    resources = ApplicationResources.from_env()
    try:
        report = validate_sqlite_transfer(source, resources.engine)
    finally:
        resources.close()
    _print_report(report)
    print("Transfer validation: OK")
    return 0


def _playhub_discover_day(day: date, force: bool) -> int:
    resources = ApplicationResources.from_env()
    client = PlayHubClient()
    try:
        service = PlayHubDiscoveryService.from_engine(resources.engine, client=client)
        result = service.sync_day(day, force=force)
    finally:
        client.close()
        resources.close()
    if result.skipped:
        print(f"Discovery {day.isoformat()}: already complete; skipped")
        return 0
    print(f"Discovery {day.isoformat()}: complete")
    print(f"Received: {result.events_received}")
    print(f"Unique in-window events: {result.unique_events}")
    print(f"Duplicate rows: {result.duplicate_rows}")
    print(f"Persisted events: {result.persisted_events}")
    print(f"Discovery run: {result.discovery_run_id}")
    return 0


def _playhub_import_event(event_id: int) -> int:
    resources = ApplicationResources.from_env()
    client = PlayHubClient()
    try:
        service = PlayHubImportService.from_engine(resources.engine, client=client)
        result = service.import_event(event_id)
    finally:
        client.close()
        resources.close()
    print(f"Event {result.event_id}: {result.status}")
    print(f"Rounds: {result.rounds_imported}/{result.rounds_expected}")
    print(f"Registrations observed: {result.registrations_found}")
    print(f"Matches imported: {result.matches_found}")
    print(f"Distinct players observed: {result.players_found}")
    if result.failed_round_ids:
        print("Failed rounds: " + ", ".join(str(value) for value in result.failed_round_ids))
    print(f"Import attempt: {result.import_attempt_id}")
    return 0



def _ratings_refresh(publication_name: str, published_by: str | None) -> int:
    resources = ApplicationResources.from_env()
    try:
        result = RatingService.from_engine(resources.engine).build_and_publish_if_changed(
            publication_name=publication_name,
            published_by=published_by,
        )
    finally:
        resources.close()
    print(f"Rating run: {result.rating_run_id}")
    print(f"Status: {result.status}")
    print(f"Inputs: {result.input_count:,}")
    print(f"Players: {result.player_count:,}")
    print(f"Input digest: {result.ordered_input_digest}")
    if result.exclusion_counts:
        print("Exclusions:")
        for reason, count in sorted(result.exclusion_counts.items()):
            print(f"  {reason}: {count:,}")
    print(f"Publication: {result.publication_name or publication_name}")
    return 0


def _ratings_publish(run_id: UUID, publication_name: str, published_by: str | None) -> int:
    resources = ApplicationResources.from_env()
    try:
        RatingService.from_engine(resources.engine).publish(
            run_id,
            publication_name=publication_name,
            published_by=published_by,
        )
    finally:
        resources.close()
    print(f"Published {run_id} as {publication_name}")
    return 0


def _teams_bootstrap(path: Path) -> int:
    definition = load_team_bootstrap(path)
    resources = ApplicationResources.from_env()
    try:
        result = TeamAdminService.from_engine(resources.engine).bootstrap(definition)
    finally:
        resources.close()
    print(f"Team: {definition.name} ({definition.slug})")
    print(f"Team ID: {result.team_id}")
    print(f"Members processed: {result.members_processed}")
    print(f"Members created: {result.members_created}")
    print(f"Memberships created: {result.memberships_created}")
    return 0



def _identity_link_discord(playhub_player_id: int, discord_user_id: int) -> int:
    resources = ApplicationResources.from_env()
    try:
        member = IdentityAdminService.from_engine(resources.engine).link_discord_for_playhub_player(
            player_id=playhub_player_id,
            discord_user_id=discord_user_id,
        )
    finally:
        resources.close()
    print(f"Linked Discord user {discord_user_id} to {member.preferred_display_name}")
    print(f"Member ID: {member.member_id}")
    print(f"Play Hub player ID: {playhub_player_id}")
    return 0


def _credential_ref_from_env_name(name: str) -> str:
    value = name.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("credential environment variable must be a valid environment-variable name")
    return f"env:{value}"


def _duels_create_connection(
    playhub_player_id: int,
    credential_env: str,
    label: str | None,
    provider_account_id: str | None,
) -> int:
    resources = ApplicationResources.from_env()
    try:
        identity = IdentityAdminService.from_engine(resources.engine)
        member = identity.member_for_playhub_player(playhub_player_id)
        connection_id = DuelsService.from_engine(resources.engine).create_connection(
            member.member_id,
            credential_ref=_credential_ref_from_env_name(credential_env),
            label=label,
            provider_account_id=provider_account_id,
        )
    finally:
        resources.close()
    print(f"Created Duels connection {connection_id}")
    print(f"Member: {member.preferred_display_name} ({member.member_id})")
    print(f"Credential reference: env:{credential_env.strip()}")
    return 0


def _duels_enqueue_sync(connection_id: UUID, generation: str | None) -> int:
    generation_value = generation.strip() if generation and generation.strip() else f"manual:{uuid4()}"
    resources = ApplicationResources.from_env()
    try:
        queued = enqueue_duels_sync(
            JobQueue.from_engine(resources.engine),
            connection_id,
            generation=generation_value,
        )
    finally:
        resources.close()
    state = "created" if queued.created else "already existed"
    print(f"Duels sync job {queued.job_id}: {state}")
    print(f"Connection: {connection_id}")
    return 0


def _catalog_enqueue_refresh(generation: str | None) -> int:
    generation_value = (
        generation.strip()
        if generation and generation.strip()
        else datetime.now(timezone.utc).date().isoformat()
    )
    resources = ApplicationResources.from_env()
    try:
        queued = enqueue_catalog_refresh(
            JobQueue.from_engine(resources.engine),
            generation=generation_value,
        )
    finally:
        resources.close()
    state = "created" if queued.created else "already existed"
    print(f"Catalog refresh job {queued.job_id}: {state}")
    print(f"Generation: {generation_value}")
    return 0

def _schedules_bootstrap() -> int:
    resources = ApplicationResources.from_env()
    try:
        results = bootstrap_platform_schedules(resources.engine)
    finally:
        resources.close()
    print("Platform schedules configured:")
    for name, scheduled_job_id in results:
        print(f"- {name}: {scheduled_job_id}")
    return 0


def _duels_schedule_sync(connection_id: UUID, interval_hours: int) -> int:
    resources = ApplicationResources.from_env()
    try:
        scheduled_job_id = upsert_duels_sync_schedule(
            resources.engine, connection_id, interval_hours=interval_hours
        )
    finally:
        resources.close()
    print(f"Duels sync schedule: {scheduled_job_id}")
    print(f"Connection: {connection_id}")
    print(f"Interval: every {interval_hours} hour(s)")
    return 0


def _ratings_leaderboard(publication_name: str, limit: int) -> int:
    resources = ApplicationResources.from_env()
    try:
        result = RatingQueryService.from_engine(resources.engine).leaderboard(
            publication_name=publication_name,
            limit=limit,
        )
    finally:
        resources.close()
    print(
        f"{result.publication.publication_name} -> {result.publication.rating_run_id} "
        f"({result.publication.policy_version})"
    )
    for entry in result.entries:
        name = entry.display_name or entry.username or f"Player {entry.player_id}"
        print(
            f"{entry.rank:>4}. {name:<28} {entry.rating:>8.1f}  "
            f"{entry.wins}-{entry.losses}-{entry.draws}  {entry.matches_played} matches"
        )
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(prog="lorcana", description="Lorcana platform administration")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("db-check", help="verify the configured PostgreSQL connection")

    discover_day = subcommands.add_parser(
        "playhub-discover-day",
        help="discover Play Hub events for one UTC calendar day",
    )
    discover_day.add_argument("day", type=date.fromisoformat, help="UTC day in YYYY-MM-DD format")
    discover_day.add_argument("--force", action="store_true", help="rerun an already completed discovery window")

    import_event = subcommands.add_parser(
        "playhub-import-event",
        help="import one Play Hub event into PostgreSQL",
    )
    import_event.add_argument("event_id", type=int, help="Play Hub event ID")

    preflight = subcommands.add_parser(
        "sqlite-preflight",
        help="audit and transform-check a frozen legacy SQLite source without PostgreSQL",
    )
    preflight.add_argument("--source", required=True, type=Path, help="path to the frozen legacy SQLite database")

    transfer = subcommands.add_parser(
        "sqlite-transfer",
        help="atomically transfer a frozen legacy SQLite source into empty migrated PostgreSQL tables",
    )
    transfer.add_argument("--source", required=True, type=Path, help="path to the frozen legacy SQLite database")
    transfer.add_argument("--batch-size", type=int, default=5_000, help="rows per PostgreSQL insert batch")

    validate = subcommands.add_parser(
        "sqlite-validate",
        help="revalidate an existing PostgreSQL transfer against the frozen SQLite source",
    )
    validate.add_argument("--source", required=True, type=Path, help="path to the frozen legacy SQLite database")

    ratings_refresh = subcommands.add_parser(
        "ratings-refresh",
        help="publish a new global Elo run only when eligible source facts changed",
    )
    ratings_refresh.add_argument("--publication-name", default="global_elo")
    ratings_refresh.add_argument("--published-by")

    ratings_publish = subcommands.add_parser(
        "ratings-publish",
        help="atomically point a publication at an already validated rating run",
    )
    ratings_publish.add_argument("run_id", type=UUID)
    ratings_publish.add_argument("--publication-name", default="global_elo")
    ratings_publish.add_argument("--published-by")

    ratings_leaderboard = subcommands.add_parser(
        "ratings-leaderboard",
        help="print a published leaderboard for operational verification",
    )
    ratings_leaderboard.add_argument("--publication-name", default="global_elo")
    ratings_leaderboard.add_argument("--limit", type=int, default=25)

    teams_bootstrap = subcommands.add_parser(
        "teams-bootstrap",
        help="idempotently load a team/member bootstrap JSON file",
    )
    teams_bootstrap.add_argument("--file", required=True, type=Path)


    identity_link_discord = subcommands.add_parser(
        "identity-link-discord",
        help="link a Discord user ID to the member owning a Play Hub player ID",
    )
    identity_link_discord.add_argument("--playhub-player-id", required=True, type=int)
    identity_link_discord.add_argument("--discord-user-id", required=True, type=int)

    duels_create = subcommands.add_parser(
        "duels-create-connection",
        help="create a Duels connection using an environment-variable credential reference",
    )
    duels_create.add_argument("--playhub-player-id", required=True, type=int)
    duels_create.add_argument(
        "--credential-env",
        required=True,
        help="environment variable name containing the Duels bearer token; the token is never stored",
    )
    duels_create.add_argument("--label")
    duels_create.add_argument("--provider-account-id")

    duels_sync = subcommands.add_parser(
        "duels-enqueue-sync",
        help="enqueue a durable Duels history/replay sync for a connection",
    )
    duels_sync.add_argument("connection_id", type=UUID)
    duels_sync.add_argument(
        "--generation",
        help="optional idempotency generation; omitted creates a fresh manual sync job",
    )

    schedules_bootstrap = subcommands.add_parser(
        "schedules-bootstrap",
        help="idempotently configure the supported recurring platform schedules",
    )

    duels_schedule = subcommands.add_parser(
        "duels-schedule-sync",
        help="idempotently configure recurring sync for one Duels connection",
    )
    duels_schedule.add_argument("connection_id", type=UUID)
    duels_schedule.add_argument("--hours", type=int, default=6, help="sync interval in hours (1-168)")

    catalog_refresh = subcommands.add_parser(
        "catalog-enqueue-refresh",
        help="enqueue a durable Lorcast card-catalog refresh",
    )
    catalog_refresh.add_argument(
        "--generation",
        help="optional idempotency generation; defaults to the current UTC date",
    )

    args = parser.parse_args()
    try:
        if args.command == "db-check":
            return _db_check()
        if args.command == "playhub-discover-day":
            return _playhub_discover_day(args.day, args.force)
        if args.command == "playhub-import-event":
            return _playhub_import_event(args.event_id)
        if args.command == "sqlite-preflight":
            return _sqlite_preflight(args.source)
        if args.command == "sqlite-transfer":
            return _sqlite_transfer(args.source, args.batch_size)
        if args.command == "sqlite-validate":
            return _sqlite_validate(args.source)
        if args.command == "ratings-refresh":
            return _ratings_refresh(args.publication_name, args.published_by)
        if args.command == "ratings-publish":
            return _ratings_publish(args.run_id, args.publication_name, args.published_by)
        if args.command == "ratings-leaderboard":
            return _ratings_leaderboard(args.publication_name, args.limit)
        if args.command == "teams-bootstrap":
            return _teams_bootstrap(args.file)
        if args.command == "identity-link-discord":
            return _identity_link_discord(args.playhub_player_id, args.discord_user_id)
        if args.command == "duels-create-connection":
            return _duels_create_connection(
                args.playhub_player_id,
                args.credential_env,
                args.label,
                args.provider_account_id,
            )
        if args.command == "duels-enqueue-sync":
            return _duels_enqueue_sync(args.connection_id, args.generation)
        if args.command == "schedules-bootstrap":
            return _schedules_bootstrap()
        if args.command == "duels-schedule-sync":
            return _duels_schedule_sync(args.connection_id, args.hours)
        if args.command == "catalog-enqueue-refresh":
            return _catalog_enqueue_refresh(args.generation)
    except (ConfigurationError, IdentityAdminError, SQLiteTransferError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

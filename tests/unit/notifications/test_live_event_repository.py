"""Execute real selection predicates; fake repositories hid source-status bugs."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select

from lorcana.db.schema.identity import members, teams, team_memberships, member_playhub_links
from lorcana.db.schema.playhub import (
    playhub_events, playhub_event_sync_state, playhub_players, playhub_registrations,
)
from lorcana.notifications.live_events import LiveEventAlertRepository
from lorcana.playhub.status import event_is_in_progress_clause

NOW = datetime(2026, 9, 26, 20, 45, tzinfo=timezone.utc)


@pytest.fixture
def connection():
    engine = create_engine("sqlite://")
    for table in (members, teams, team_memberships, member_playhub_links,
                  playhub_events, playhub_event_sync_state, playhub_players, playhub_registrations):
        table.create(engine)
    with engine.begin() as conn:
        yield conn
    engine.dispose()


def event(connection, event_id=772891, **overrides):
    values = dict(event_id=event_id, name="Set Championship",
                  start_datetime=NOW - timedelta(hours=2), end_datetime=NOW + timedelta(hours=5),
                  timezone="America/Chicago", display_status="inProgress", event_status="SCHEDULED",
                  lifecycle_status="EVENT_IN_PROGRESS", last_synced=NOW,
                  source_url=f"https://tcg.ravensburgerplay.com/events/{event_id}")
    values.update(overrides)
    connection.execute(playhub_events.insert().values(**values))


def link_team(connection):
    member_id, team_id = uuid4(), uuid4()
    connection.execute(members.insert().values(member_id=member_id, preferred_display_name="Jacob",
                       status="active", created_at=NOW, updated_at=NOW))
    connection.execute(teams.insert().values(team_id=team_id, slug="inkspire", name="Inkspire",
                       status="active", created_at=NOW, updated_at=NOW))
    connection.execute(team_memberships.insert().values(team_membership_id=uuid4(), team_id=team_id,
                       member_id=member_id, role="member", joined_at=NOW))
    connection.execute(member_playhub_links.insert().values(player_id=1, member_id=member_id,
                       linked_at=NOW))
    connection.execute(playhub_players.insert().values(player_id=1))
    connection.execute(playhub_registrations.insert().values(registration_id=1001, event_id=772891,
                       player_id=1, registration_status="COMPLETE", last_synced=NOW))


def eligible(connection):
    return LiveEventAlertRepository().eligible_events(
        connection, team_slug="inkspire", now=NOW, fresh_after=NOW - timedelta(minutes=10))


def test_event_772891_is_discovered_without_registration_then_eligible_after_import(connection):
    event(connection)
    repo = LiveEventAlertRepository()
    assert repo.potential_event_ids(connection, team_slug="inkspire", now=NOW, limit=50) == (772891,)
    assert not eligible(connection)  # Discovery alone must not authorize posting.
    link_team(connection)
    assert [row["event_id"] for row in eligible(connection)] == [772891]


@pytest.mark.parametrize("column,value", [
    ("display_status", "inProgress"), ("lifecycle_status", "EVENT_IN_PROGRESS"),
    ("event_status", "IN_PROGRESS"), ("display_status", " live "),
])
def test_raw_active_statuses_are_recognized_independently(connection, column, value):
    event(connection, display_status=None, event_status="SCHEDULED", lifecycle_status=None)
    connection.execute(playhub_events.update().values(**{column: value}))
    assert connection.execute(select(playhub_events.c.event_id).where(event_is_in_progress_clause())).scalar() == 772891


@pytest.mark.parametrize("changes", [
    {"lifecycle_status": "EVENT_FINISHED"}, {"event_status": "CANCELLED"},
    {"display_status": "finished"},
    {"display_status": "scheduled", "lifecycle_status": None},
    {"start_datetime": NOW + timedelta(hours=1)}, {"end_datetime": NOW},
    {"last_synced": NOW - timedelta(minutes=11)},
])
def test_finished_future_expired_stale_and_merely_scheduled_events_are_not_eligible(connection, changes):
    event(connection, **changes)
    link_team(connection)
    assert not eligible(connection)


@pytest.mark.parametrize("status", ["DROPPED", "CANCELLED", "PENDING", None])
def test_nonparticipating_registrations_do_not_announce(connection, status):
    event(connection)
    link_team(connection)
    connection.execute(playhub_registrations.update().values(registration_status=status))
    assert not eligible(connection)


def test_stale_registration_or_inactive_team_does_not_announce(connection):
    event(connection)
    link_team(connection)
    connection.execute(playhub_registrations.update().values(last_synced=NOW - timedelta(minutes=11)))
    assert not eligible(connection)
    connection.execute(playhub_registrations.update().values(last_synced=NOW))
    connection.execute(team_memberships.update().values(ended_at=NOW))
    assert not eligible(connection)


def test_bounded_scan_rotates_even_after_network_failure_and_preserves_import_state(connection):
    for event_id in (1, 2, 3):
        event(connection, event_id)
    event(connection, 4, start_datetime=NOW + timedelta(hours=1))
    event(connection, 5, end_datetime=NOW)
    event(connection, 6, start_datetime=NOW - timedelta(days=2))
    repo = LiveEventAlertRepository()
    def candidates(now=NOW):
        return repo.potential_event_ids(connection, team_slug="inkspire", now=now, limit=2)
    assert candidates() == (1, 2)
    connection.execute(playhub_event_sync_state.insert().values(
        event_id=1, state="complete", last_success_at=NOW - timedelta(hours=1)))
    for event_id in candidates():
        repo.record_refresh_attempt(connection, event_id=event_id, now=NOW)
    # No importer success is needed to advance past a failed fetch.
    assert candidates() == (3,)
    assert candidates(NOW + timedelta(minutes=5)) == (3, 1)
    state = connection.execute(select(playhub_event_sync_state).where(
        playhub_event_sync_state.c.event_id == 1)).mappings().one()
    assert state["state"] == "complete"
    assert state["last_success_at"] is not None

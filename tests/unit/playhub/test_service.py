from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from lorcana.playhub.client import PlayHubClientError
from lorcana.playhub.service import PlayHubImportService

NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)



from support.playhub_payloads import raw_event, raw_match, raw_standings


class FakeClient:
    def __init__(self, *, standings=None, matches=None):
        self.standings = {} if standings is None else standings
        self.matches = {} if matches is None else matches
        self.match_calls = []
        self.standings_calls = []

    def fetch_event_html(self, event_id):
        raise AssertionError("event_data should make HTML fetch unnecessary")

    def fetch_all_standings(self, round_id):
        self.standings_calls.append(round_id)
        result = self.standings.get(round_id, [])
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_all_round_matches(self, round_id):
        self.match_calls.append(round_id)
        result = self.matches.get(round_id, [])
        if isinstance(result, Exception):
            raise result
        return result


class FakeRepository:
    def __init__(self):
        self.stores = {}
        self.events = {}
        self.phases = {}
        self.rounds = {}
        self.players = {}
        self.registrations = {}
        self.matches = {}
        self.attempts = {}
        self.sync = {}

    def upsert_store(self, _c, row): self.stores[row.store_id] = row
    def upsert_event(self, _c, row): self.events[row.event_id] = row
    def upsert_phase(self, _c, row): self.phases[row.phase_id] = row
    def upsert_round(self, _c, row): self.rounds[row.round_id] = row
    def upsert_player(self, _c, row): self.players[row.player_id] = row
    def upsert_registration(self, _c, row): self.registrations[row.registration_id] = row
    def upsert_match(self, _c, row): self.matches[row.match_id] = row

    def start_import_attempt(self, _c, **values):
        self.attempts[values["import_attempt_id"]] = {**values, "status": "running"}

    def finish_import_attempt(self, _c, **values):
        self.attempts[values["import_attempt_id"]].update(values)

    def set_event_sync_state(self, _c, **values):
        old = self.sync.get(values["event_id"], {})
        if values.get("last_success_at") is None and old.get("last_success_at") is not None:
            values["last_success_at"] = old["last_success_at"]
        self.sync[values["event_id"]] = {**old, **values}

    def count_distinct_event_players(self, _c, event_id):
        ids = {r.player_id for r in self.registrations.values() if r.event_id == event_id}
        for match in self.matches.values():
            if match.event_id == event_id:
                ids.update(value for value in (match.player1_id, match.player2_id) if value is not None)
        return len(ids)


@contextmanager
def fake_transaction():
    yield object()


def service(client, repository, uuids):
    iterator = iter(uuids)
    return PlayHubImportService(
        client=client,
        repository=repository,
        transaction_factory=lambda: fake_transaction(),
        clock=lambda: NOW,
        uuid_factory=lambda: next(iterator),
    )


def test_complete_import_persists_source_facts_and_attempt_state():
    repository = FakeRepository()
    client = FakeClient(standings={101: raw_standings()}, matches={101: [raw_match()]})
    attempt_id = UUID("00000000-0000-0000-0000-000000000001")

    result = service(client, repository, [attempt_id]).import_event(1, event_data=raw_event())

    assert result.status == "complete"
    assert result.rounds_expected == result.rounds_imported == 1
    assert result.registrations_found == 2
    assert result.matches_found == 1
    assert result.players_found == 2
    assert repository.matches[500].player1_score == 2
    assert repository.matches[500].player2_score == 0
    assert repository.attempts[attempt_id]["status"] == "complete"
    assert repository.sync[1]["state"] == "complete"
    assert repository.sync[1]["last_success_at"] == NOW


def test_partial_round_failure_keeps_successful_round_and_records_failed_round_ids():
    repository = FakeRepository()
    client = FakeClient(
        standings={102: raw_standings()},
        matches={101: [raw_match(500)], 102: PlayHubClientError("round failed")},
    )
    result = service(
        client, repository, [UUID("00000000-0000-0000-0000-000000000002")]
    ).import_event(1, event_data=raw_event(rounds=2))

    assert result.status == "partial"
    assert result.rounds_expected == 2
    assert result.rounds_imported == 1
    assert result.matches_found == 1
    assert result.failed_round_ids == (102,)
    assert set(repository.matches) == {500}
    assert repository.sync[1]["state"] == "partial"


def test_event_with_no_generated_play_rounds_is_no_results():
    repository = FakeRepository()
    client = FakeClient()
    result = service(
        client, repository, [UUID("00000000-0000-0000-0000-000000000003")]
    ).import_event(1, event_data=raw_event(generated=False))

    assert result.status == "no_results"
    assert result.rounds_expected == 0
    assert client.match_calls == []
    assert repository.sync[1]["state"] == "no_results"


def test_failure_after_attempt_start_is_recorded_and_reraised():
    repository = FakeRepository()
    client = FakeClient(standings={101: PlayHubClientError("standings unavailable")})
    attempt_id = UUID("00000000-0000-0000-0000-000000000004")
    importer = service(client, repository, [attempt_id])

    with pytest.raises(PlayHubClientError, match="standings unavailable"):
        importer.import_event(1, event_data=raw_event())

    assert repository.attempts[attempt_id]["status"] == "failed"
    assert repository.attempts[attempt_id]["error_category"] == "client_error"
    assert repository.sync[1]["state"] == "failed"


def test_retry_is_idempotent_for_source_entities_but_keeps_attempt_history():
    repository = FakeRepository()
    client = FakeClient(standings={101: raw_standings()}, matches={101: [raw_match()]})
    ids = [
        UUID("00000000-0000-0000-0000-000000000005"),
        UUID("00000000-0000-0000-0000-000000000006"),
    ]
    importer = service(client, repository, ids)

    first = importer.import_event(1, event_data=raw_event())
    second = importer.import_event(1, event_data=raw_event())

    assert first.status == second.status == "complete"
    assert len(repository.events) == 1
    assert len(repository.rounds) == 1
    assert len(repository.registrations) == 2
    assert len(repository.matches) == 1
    assert len(repository.attempts) == 2


def test_first_round_pairings_supply_real_registrations_before_standings():
    repository = FakeRepository()
    event = raw_event()
    first_round = event["tournament_phases"][0]["rounds"][0]
    first_round.update(status="IN_PROGRESS", standings_status="NOT_GENERATED")
    match = raw_match()
    match["status"] = "IN_PROGRESS"
    for relationship, standing in zip(match["player_match_relationships"], raw_standings()):
        relationship["user_event_status"] = dict(standing["user_event_status"], registration_status="COMPLETE")
    client = FakeClient(matches={101: [match]})
    result = service(client, repository, [UUID(int=1)]).import_event(1, event_data=event)
    assert not client.standings_calls
    assert result.registrations_found == 2
    assert {r.registration_status for r in repository.registrations.values()} == {"COMPLETE"}
    assert {r.last_synced for r in repository.registrations.values()} == {NOW}


def test_pairings_do_not_replace_existing_ranked_standings():
    repository = FakeRepository()
    match = raw_match()
    for relationship, standing in zip(match["player_match_relationships"], raw_standings()):
        relationship["user_event_status"] = dict(standing["user_event_status"], matches_won=99)
    client = FakeClient(standings={101: raw_standings()}, matches={101: [match]})
    service(client, repository, [UUID(int=1)]).import_event(1, event_data=raw_event())
    assert repository.registrations[1001].placement == 1
    assert repository.registrations[1001].matches_won == 1

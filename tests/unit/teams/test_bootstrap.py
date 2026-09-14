from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from uuid import UUID

import pytest

from lorcana.teams.service import TeamAdminService, load_team_bootstrap
from lorcana.teams.types import TeamBootstrap, TeamBootstrapMember

NOW = datetime(2026, 9, 13, 22, 0, tzinfo=timezone.utc)


def test_load_inkspire_bootstrap_preserves_all_legacy_player_ids():
    definition = load_team_bootstrap(__import__("pathlib").Path("data/bootstrap/inkspire.json"))
    assert definition.slug == "inkspire"
    assert definition.name == "Inkspire"
    assert len(definition.members) == 13
    assert {m.playhub_player_id for m in definition.members} == {
        7504, 9876, 7573, 75367, 29844, 29845, 23014, 244441,
        80711, 9109, 12853, 80712, 22573,
    }


def test_bootstrap_validation_rejects_duplicate_provider_ids(tmp_path):
    path = tmp_path / "team.json"
    path.write_text(json.dumps({
        "team": {"slug": "x", "name": "X"},
        "members": [
            {"preferred_display_name": "A", "playhub_player_id": 1},
            {"preferred_display_name": "B", "playhub_player_id": 1},
        ],
    }))
    with pytest.raises(ValueError, match="Duplicate Play Hub player ID"):
        load_team_bootstrap(path)


class FakeRepository:
    def __init__(self):
        self.team_id = None
        self.links = {}
        self.names = {}
        self.memberships = set()

    def upsert_team(self, _c, *, team_id, slug, name, now):
        if self.team_id is None:
            self.team_id = team_id
        return self.team_id

    def member_id_for_playhub_player(self, _c, player_id):
        return self.links.get(player_id)

    def create_member(self, _c, *, member_id, preferred_display_name, now):
        self.names[member_id] = preferred_display_name

    def update_member_name(self, _c, *, member_id, preferred_display_name, now):
        self.names[member_id] = preferred_display_name

    def link_playhub_player(self, _c, *, member_id, player_id, now, linked_by):
        self.links[player_id] = member_id

    def ensure_active_membership(self, _c, *, membership_id, team_id, member_id, role, now):
        key = (team_id, member_id)
        if key in self.memberships:
            return False
        self.memberships.add(key)
        return True


@contextmanager
def fake_transaction():
    yield object()


def test_bootstrap_is_idempotent_and_does_not_match_people_by_name():
    ids = iter(UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(1, 20))
    repo = FakeRepository()
    service = TeamAdminService(
        repository=repo,
        transaction_factory=fake_transaction,
        clock=lambda: NOW,
        uuid_factory=lambda: next(ids),
    )
    definition = TeamBootstrap(
        slug="inkspire",
        name="Inkspire",
        members=(
            TeamBootstrapMember("Same Name", 100),
            TeamBootstrapMember("Same Name", 200),
        ),
    )

    first = service.bootstrap(definition)
    second = service.bootstrap(definition)

    assert first.members_created == 2
    assert first.memberships_created == 2
    assert second.members_created == 0
    assert second.memberships_created == 0
    assert repo.links[100] != repo.links[200]

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from lorcana.identity.service import IdentityAdminError, IdentityAdminService

MEMBER_ID = UUID("00000000-0000-0000-0000-000000000123")
NOW = datetime(2026, 9, 13, 22, 0, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self):
        self.members = {
            7504: {
                "member_id": MEMBER_ID,
                "preferred_display_name": "Jacob",
            }
        }
        self.discord_links = {}

    def member_for_playhub_player(self, _connection, player_id):
        return self.members.get(player_id)

    def link_discord_account(self, _connection, *, discord_user_id, member_id, linked_at):
        self.discord_links[discord_user_id] = (member_id, linked_at)


@contextmanager
def fake_connection():
    yield object()


def service(repo, *, clock=lambda: NOW):
    return IdentityAdminService(
        repository=repo,
        read_connection_factory=fake_connection,
        transaction_factory=fake_connection,
        clock=clock,
    )


def test_resolves_member_from_explicit_playhub_link():
    result = service(FakeRepository()).member_for_playhub_player(7504)
    assert result.member_id == MEMBER_ID
    assert result.preferred_display_name == "Jacob"


def test_links_discord_account_to_existing_member():
    repo = FakeRepository()
    result = service(repo).link_discord_for_playhub_player(
        player_id=7504,
        discord_user_id=123456789,
    )
    assert result.member_id == MEMBER_ID
    assert repo.discord_links[123456789] == (MEMBER_ID, NOW)


def test_missing_playhub_link_is_rejected_without_creating_identity():
    repo = FakeRepository()
    with pytest.raises(IdentityAdminError, match="No active member"):
        service(repo).link_discord_for_playhub_player(
            player_id=999999,
            discord_user_id=123456789,
        )
    assert repo.discord_links == {}


def test_provider_ids_must_be_positive():
    repo = FakeRepository()
    with pytest.raises(ValueError, match="Play Hub"):
        service(repo).member_for_playhub_player(0)
    with pytest.raises(ValueError, match="Discord"):
        service(repo).link_discord_for_playhub_player(player_id=7504, discord_user_id=0)

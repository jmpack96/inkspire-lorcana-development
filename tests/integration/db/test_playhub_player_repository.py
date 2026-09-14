from datetime import datetime, timezone

import pytest

from lorcana.db.tx import transaction
from lorcana.playhub.repository import PlayHubRepository
from lorcana.playhub.types import PlayHubPlayer

pytestmark = pytest.mark.integration


def test_player_repository_upsert_is_idempotent(db_engine):
    repository = PlayHubRepository()
    now = datetime.now(timezone.utc)
    player_id = 9_876_543_210
    with transaction(db_engine) as connection:
        repository.upsert_player(connection, PlayHubPlayer(player_id, "First Name", "first", now, now))
        repository.upsert_player(connection, PlayHubPlayer(player_id, "Updated Name", "updated", now, now))
        result = repository.get_player(connection, player_id)
        assert result is not None
        assert result.display_name == "Updated Name"
        assert result.username == "updated"

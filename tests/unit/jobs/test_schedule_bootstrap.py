from __future__ import annotations

from uuid import UUID

import pytest

import lorcana.jobs.bootstrap as bootstrap_module
from lorcana.jobs.bootstrap import default_platform_schedules, upsert_duels_sync_schedule
from lorcana.jobs.kinds import (
    CATALOG_REFRESH_LORCAST,
    MAINTENANCE_PRUNE_JOBS,
    PLAYHUB_DISCOVER_WINDOW,
    PLAYHUB_IMPORT_SWEEP,
    RATINGS_BUILD_PUBLISH,
)


def test_default_schedules_cover_shared_production_pipeline_without_account_specific_duels():
    definitions = {item.name: item for item in default_platform_schedules()}
    assert set(definitions) == {
        "playhub-discover-upcoming",
        "playhub-import-sweep",
        "ratings-global-daily",
        "maintenance-prune-jobs",
        "catalog-lorcast-daily",
    }
    assert definitions["playhub-discover-upcoming"].kind == PLAYHUB_DISCOVER_WINDOW
    discovery = definitions["playhub-discover-upcoming"]
    assert discovery.payload["anchor_date"] == "$scheduled_date"
    assert discovery.payload["lookback_days"] == 30
    assert discovery.payload["lookahead_days"] == 30
    assert definitions["playhub-import-sweep"].kind == PLAYHUB_IMPORT_SWEEP
    assert definitions["playhub-import-sweep"].payload["generation"] == "$scheduled_at"
    assert definitions["ratings-global-daily"].kind == RATINGS_BUILD_PUBLISH
    assert definitions["catalog-lorcast-daily"].kind == CATALOG_REFRESH_LORCAST
    assert definitions["maintenance-prune-jobs"].kind == MAINTENANCE_PRUNE_JOBS
    assert definitions["maintenance-prune-jobs"].payload["retention_days"] == 30
    assert all(not item.kind.startswith("duels.") for item in definitions.values())

    import_sweep = definitions["playhub-import-sweep"]

    assert import_sweep.payload["lookback_days"] == 90
    assert import_sweep.payload["retry_minutes"] == 180


def test_duels_schedule_is_connection_scoped_and_contains_no_secret(monkeypatch):
    connection_id = UUID("00000000-0000-0000-0000-000000000777")
    captured = {}

    class Service:
        def upsert(self, name, kind, **kwargs):
            captured.update(name=name, kind=kind, **kwargs)
            return UUID(int=9)

    monkeypatch.setattr(
        bootstrap_module.ScheduledJobService,
        "from_engine",
        classmethod(lambda cls, engine: Service()),
    )

    result = upsert_duels_sync_schedule(object(), connection_id, interval_hours=4)
    assert result == UUID(int=9)
    assert captured["name"] == f"duels-sync-{connection_id}"
    assert captured["payload"] == {"connection_id": str(connection_id)}
    assert captured["schedule_spec"] == {"type": "interval", "seconds": 4 * 60 * 60}
    assert "token" not in str(captured).lower()
    assert "credential" not in str(captured).lower()


@pytest.mark.parametrize("hours", [0, 169])
def test_duels_schedule_rejects_unreasonable_interval(hours):
    with pytest.raises(ValueError, match="interval_hours"):
        upsert_duels_sync_schedule(object(), UUID(int=1), interval_hours=hours)

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from lorcana.cache import ReadCache


def test_expiry_key_change_and_copy_isolation():
    now = [0]
    cache = ReadCache(seconds=60, clock=lambda: now[0])
    calls = []

    def build():
        calls.append(1)
        return {"rows": [len(calls)]}

    first = cache.get("team", build)
    first["rows"].append(999)
    assert cache.get("team", build) == {"rows": [1]}
    now[0] = 60
    assert cache.get("team", build) == {"rows": [2]}
    assert cache.get("different roster", build) == {"rows": [3]}


def test_failed_refresh_does_not_extend_expired_value():
    cache = ReadCache(seconds=0)
    assert cache.get("team", lambda: 1) == 1
    with pytest.raises(ValueError):
        cache.get("team", lambda: (_ for _ in ()).throw(ValueError()))
    assert cache.get("team", lambda: 2) == 2


def test_concurrent_requests_share_a_single_build():
    cache = ReadCache()
    entered, release = Event(), Event()
    calls = []

    def build():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {"count": 1}

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.get, "team", build)
        assert entered.wait(5)
        second = executor.submit(cache.get, "team", build)
        release.set()
        assert first.result() == second.result() == {"count": 1}
    assert len(calls) == 1

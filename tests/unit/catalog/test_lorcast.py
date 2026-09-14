from __future__ import annotations

import pytest

from lorcana.catalog.lorcast import LorcastClient, LorcastError


class Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, timeout):
        self.urls.append((url, timeout))
        return self.responses.pop(0)


def test_complete_snapshot_maps_lorcast_to_duels_set_number_ids_and_paces_requests():
    sleeps = []
    session = Session([
        Response(200, {"results": [
            {"code": "12", "name": "Set Twelve", "released_at": "2026-01-01"},
            {"code": "13", "name": "Set Thirteen", "released_at": "2026-05-01"},
        ]}),
        Response(200, [{
            "id": "crd_one",
            "name": "Hamm",
            "version": "Piggy Bank",
            "collector_number": "11",
            "lang": "en",
            "ink": "Sapphire",
            "cost": 2,
            "inkwell": True,
            "type": ["Character"],
            "classifications": ["Storyborn", "Ally"],
            "text": "Rules",
            "set": {"code": "12", "name": "Set Twelve"},
        }]),
        Response(200, [{
            "id": "crd_two",
            "name": "Dual Card",
            "version": None,
            "collector_number": "5",
            "lang": "en",
            "ink": ["Ruby", "Sapphire"],
            "type": ["Action", "Song"],
            "set": {"code": "13", "name": "Set Thirteen"},
        }, {
            "id": "foreign",
            "name": "Ignored",
            "collector_number": "6",
            "lang": "fr",
            "set": {"code": "13", "name": "Set Thirteen"},
        }]),
    ])
    client = LorcastClient(session=session, sleeper=sleeps.append, request_delay_seconds=0.075)
    payload, metadata = client.complete_english_snapshot()

    assert [card["id"] for card in payload["cards"]] == ["12-11", "13-5"]
    first = payload["cards"][0]
    assert first["name"] == "Hamm - Piggy Bank"
    assert first["ink_colors"] == ["Sapphire"]
    assert first["source_id"] == "crd_one"
    assert payload["cards"][1]["ink_colors"] == ["Ruby", "Sapphire"]
    assert payload["cards"][1]["card_type"] == "Action/Song"
    assert metadata["set_count"] == 2
    assert sleeps == [0.075, 0.075]


def test_lorcast_retries_429_and_5xx_then_returns_json():
    sleeps = []
    session = Session([
        Response(429, {}),
        Response(503, {}),
        Response(200, {"results": []}),
    ])
    client = LorcastClient(session=session, sleeper=sleeps.append, request_delay_seconds=0, max_attempts=3)
    assert client.sets() == []
    assert sleeps == [1, 2]


def test_lorcast_rejects_permanent_http_and_bad_shapes():
    client = LorcastClient(session=Session([Response(404, {})]), sleeper=lambda _: None, max_attempts=1)
    with pytest.raises(LorcastError, match="HTTP 404"):
        client.sets()

    client = LorcastClient(session=Session([Response(200, {"unexpected": []})]), sleeper=lambda _: None)
    with pytest.raises(LorcastError, match="unexpected payload"):
        client.sets()

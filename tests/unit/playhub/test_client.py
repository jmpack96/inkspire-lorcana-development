from __future__ import annotations

import requests
import pytest

from lorcana.playhub.client import PlayHubClient, PlayHubClientError


class FakeResponse:
    def __init__(self, status_code=200, *, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


def test_retryable_http_honors_retry_after():
    sleeps = []
    session = FakeSession([
        FakeResponse(429, headers={"Retry-After": "7"}),
        FakeResponse(200, text="ok"),
    ])
    client = PlayHubClient(session=session, sleep=sleeps.append, max_attempts=2)

    assert client.fetch_event_html(123) == "ok"
    assert len(session.calls) == 2
    assert sleeps == [7.0]


def test_non_retryable_http_fails_immediately():
    sleeps = []
    session = FakeSession([FakeResponse(403)])
    client = PlayHubClient(session=session, sleep=sleeps.append)

    with pytest.raises(PlayHubClientError, match="HTTP 403"):
        client.fetch_event_html(123)
    assert len(session.calls) == 1
    assert sleeps == []


def test_network_errors_retry_then_raise_clean_client_error():
    sleeps = []
    session = FakeSession([requests.Timeout("x"), requests.ConnectionError("y")])
    client = PlayHubClient(session=session, sleep=sleeps.append, max_attempts=2, initial_retry_seconds=1)

    with pytest.raises(PlayHubClientError, match="after 2 attempts"):
        client.fetch_event_html(123)
    assert sleeps == [1]


def test_match_pagination_collects_pages_and_delays_between_them():
    sleeps = []
    session = FakeSession([
        FakeResponse(payload={"results": [{"id": 1}], "next_page_number": 2}),
        FakeResponse(payload={"results": [{"id": 2}], "next_page_number": None}),
    ])
    client = PlayHubClient(session=session, sleep=sleeps.append, request_delay_seconds=0.25)

    assert client.fetch_all_round_matches(99) == [{"id": 1}, {"id": 2}]
    assert [call[1]["params"]["page"] for call in session.calls] == [1, 2]
    assert sleeps == [0.25]


def test_pagination_loop_is_rejected():
    session = FakeSession([
        FakeResponse(payload={"results": [], "next_page_number": 1}),
    ])
    client = PlayHubClient(session=session, sleep=lambda _: None)
    with pytest.raises(PlayHubClientError, match="Pagination loop"):
        client.fetch_all_standings(99)

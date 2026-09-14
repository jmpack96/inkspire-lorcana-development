
from lorcana.duels.client import DuelsClient


class FakeResponse:
    def __init__(self, *, payload=None, content=b"x", status_code=200, headers=None):
        self._payload = payload
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self):
        pass


def test_history_request_uses_bearer_token():
    session = FakeSession([FakeResponse(payload={"games": [], "next_cursor": None})])
    client = DuelsClient("secret", session=session)
    page = client.fetch_history_page()
    assert page.games == ()
    headers = session.calls[0][1]["headers"]
    assert headers["Authorization"] == "Bearer secret"


def test_external_signed_replay_url_does_not_receive_bearer_token():
    session = FakeSession([FakeResponse(content=b"artifact")])
    client = DuelsClient("secret", session=session)
    assert client.download_replay("https://storage.example.com/signed/replay.gz") == b"artifact"
    headers = session.calls[0][1]["headers"]
    assert "Authorization" not in headers


def test_duels_host_replay_can_receive_bearer_token():
    session = FakeSession([FakeResponse(content=b"artifact")])
    client = DuelsClient("secret", session=session)
    client.download_replay("https://duels.ink/api/replay/1")
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer secret"

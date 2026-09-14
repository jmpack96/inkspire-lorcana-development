import json
from pathlib import Path

import pytest

from lorcana.playhub.parser import PlayHubParseError, extract_event_data

FIXTURES = Path(__file__).parents[2] / "fixtures" / "playhub"


def hydration(text):
    return "<script>self.__next_f.push(" + json.dumps([1, text]) + ")</script>"


def test_reduced_failing_public_event():
    expected = json.loads((FIXTURES / "event_174256.json").read_text())
    html = (FIXTURES / "event_174256.html").read_text()
    assert extract_event_data(html, 174256) == expected


def test_preserves_nested_escapes_and_braces():
    event = {
        "id": 123,
        "name": 'A "quoted" event {with braces}',
        "description": "Newline\nTab\tPath C:\\Players\\test; literal \\n; café 🃏",
        "nested": {"values": [None, True, 'a\\"b', "}"]},
    }
    assert extract_event_data(hydration("3a:" + json.dumps(event)), 123) == event


def test_split_hydration_chunks():
    event = {"id": 123, "description": "hello\nworld"}
    text = "3a:" + json.dumps(event)
    for split in range(1, len(text)):
        html = hydration(text[:split]) + hydration(text[split:])
        assert extract_event_data(html, 123) == event


def test_unescaped_object_with_whitespace_and_trailing_stream():
    html = '<script>3a:{ "id" : 123, "name": "Example"}\n3b:[]</script>'
    assert extract_event_data(html, 123) == {"id": 123, "name": "Example"}


def test_ignores_other_events_and_id_only_query_reference():
    text = '1:{"id":123}\n2:{"id":1234,"name":"Other"}\n3:{"id":123,"name":"Target"}\n'
    html = '<script>self.__next_f.push([0])</script>' + hydration(text)
    assert extract_event_data(html, 123)["name"] == "Target"


def test_missing_event_fails():
    with pytest.raises(PlayHubParseError, match="Could not locate.*123"):
        extract_event_data(hydration('1:{"id":1234,"name":"Other"}'), 123)


@pytest.mark.parametrize("text", ['1:{"id":123,"name":"unfinished', r'1:{"id":123,"name":"bad\P"}'])
def test_invalid_inner_json_is_not_silently_repaired(text):
    with pytest.raises(PlayHubParseError, match="Invalid embedded event JSON"):
        extract_event_data(hydration(text), 123)


def test_invalid_outer_json_fails():
    with pytest.raises(PlayHubParseError, match="Invalid Next.js hydration JSON"):
        extract_event_data('<script>self.__next_f.push([1,"unfinished)</script>', 123)

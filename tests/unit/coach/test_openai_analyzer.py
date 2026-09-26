import json

import pytest

from lorcana.coach.openai_analyzer import (
    OPENAI_RESPONSES_URL,
    OpenAIAnalyzerError,
    OpenAIResponsesCoachAnalyzer,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def completed_payload():
    structured = {
        "summary": "Good recovery after an early sequencing loss.",
        "findings": [
            {
                "claim_basis": "strategic_inference",
                "rule_citations": [],
                "card_citations": [],
                "category": "sequencing",
                "impact": "medium",
                "confidence": 0.92,
                "claim_type": "inference",
                "observation": "The action committed resources before the draw.",
                "recommendation": "Resolve the available draw first.",
                "evidence_action_ids": [4],
                "evidence_turns": [2],
            }
        ],
    }
    return {
        "status": "completed",
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": json.dumps(structured)}],
        }],
        "usage": {"input_tokens": 123, "output_tokens": 45},
    }


def test_openai_analyzer_uses_private_strict_structured_response_request():
    session = FakeSession([FakeResponse(200, completed_payload())])
    analyzer = OpenAIResponsesCoachAnalyzer(
        api_key="sk-test-secret",
        model="gpt-5.4",
        session=session,
    )

    result = analyzer.analyze(grounded_evidence())

    assert result.summary.startswith("Good recovery")
    assert result.findings[0].evidence_action_ids == (4,)
    assert result.usage["input_tokens"] == 123
    assert result.usage["review_budget"]["allowed"]
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == OPENAI_RESPONSES_URL
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test-secret"
    assert kwargs["json"]["store"] is False
    assert kwargs["json"]["model"] == "gpt-5.4"
    assert kwargs["json"]["text"]["format"]["type"] == "json_schema"
    assert kwargs["json"]["text"]["format"]["strict"] is True
    assert kwargs["json"]["text"]["format"]["schema"]["additionalProperties"] is False


def test_openai_analyzer_does_not_retry_429_by_default():
    session = FakeSession([FakeResponse(429, {})])
    analyzer = OpenAIResponsesCoachAnalyzer(api_key="secret", model="gpt-5.4", session=session)
    with pytest.raises(OpenAIAnalyzerError, match="429"):
        analyzer.analyze(grounded_evidence())
    assert len(session.calls) == 1


def test_openai_analyzer_does_not_retry_non_transient_4xx_or_echo_body():
    session = FakeSession([FakeResponse(400, {"error": "sensitive provider body"})])
    analyzer = OpenAIResponsesCoachAnalyzer(
        api_key="secret",
        model="gpt-5.4",
        session=session,
    )

    with pytest.raises(OpenAIAnalyzerError, match=r"OpenAI HTTP 400") as caught:
        analyzer.analyze(grounded_evidence())

    assert "sensitive provider body" not in str(caught.value)
    assert len(session.calls) == 1


def test_openai_analyzer_rejects_refusal_and_invalid_json():
    refusal = {
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
    }
    analyzer = OpenAIResponsesCoachAnalyzer(
        api_key="secret", model="gpt-5.4", session=FakeSession([FakeResponse(200, refusal)])
    )
    with pytest.raises(OpenAIAnalyzerError, match="refused"):
        analyzer.analyze(grounded_evidence())

    invalid = {
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "not-json"}]}],
    }
    analyzer = OpenAIResponsesCoachAnalyzer(
        api_key="secret", model="gpt-5.4", session=FakeSession([FakeResponse(200, invalid)])
    )
    with pytest.raises(OpenAIAnalyzerError, match="valid JSON"):
        analyzer.analyze(grounded_evidence())


def test_openai_analyzer_close_only_closes_owned_session(monkeypatch):
    class OwnedSession(FakeSession):
        def __init__(self):
            super().__init__([])

    owned = OwnedSession()
    monkeypatch.setattr("lorcana.coach.openai_analyzer.requests.Session", lambda: owned)
    analyzer = OpenAIResponsesCoachAnalyzer(api_key="secret", model="gpt-5.4")
    analyzer.close()
    assert owned.closed is True

    injected = FakeSession([])
    analyzer = OpenAIResponsesCoachAnalyzer(api_key="secret", model="gpt-5.4", session=injected)
    analyzer.close()
    assert injected.closed is False


def grounded_evidence():
    return {"normalization": {"effective_actions": [{"seq": 4, "gameplay_turn": 2,
            "actor_is_perspective": True, "type": "play", "card_id": "3-16"}]},
            "rules": {"status": "available", "citations": {"CR:test:p1": {"text": "drawing cards before another action"}}},
            "catalog": {"facts": {"3-16": {"name": "Fixture", "rules_text": "drawing cards"}}, "missing_card_ids": []}}


def test_missing_rules_or_cards_blocks_before_network_request():
    session = FakeSession([])
    analyzer = OpenAIResponsesCoachAnalyzer(api_key="secret", model="gpt-5.4", session=session)
    with pytest.raises(OpenAIAnalyzerError, match="rules reference"):
        analyzer.analyze({})
    evidence = grounded_evidence()
    evidence["catalog"]["missing_card_ids"] = ["3-223"]
    with pytest.raises(OpenAIAnalyzerError, match="missing card"):
        analyzer.analyze(evidence)
    assert session.calls == []


def test_model_cannot_publish_invented_rule_citation():
    payload = completed_payload()
    value = json.loads(payload["output"][0]["content"][0]["text"])
    value["findings"][0]["rule_citations"] = ["CR:fake:p999"]
    payload["output"][0]["content"][0]["text"] = json.dumps(value)
    analyzer = OpenAIResponsesCoachAnalyzer(api_key="secret", model="gpt-5.4",
        session=FakeSession([FakeResponse(200, payload)]))
    with pytest.raises(OpenAIAnalyzerError, match="unavailable rule"):
        analyzer.analyze(grounded_evidence())


def test_oversize_selected_evidence_is_blocked_before_paid_call():
    from lorcana.coach.review_plan import ReviewBlocked
    session = FakeSession([])
    analyzer = OpenAIResponsesCoachAnalyzer(api_key="secret", model="gpt-5.4", session=session)
    evidence = grounded_evidence()
    evidence["rules"]["citations"]["CR:test:p1"]["text"] = "drawing " * 30000
    with pytest.raises(ReviewBlocked, match="before API call"):
        analyzer.analyze(evidence)
    assert session.calls == []


def test_model_output_schema_has_no_confidence_or_fact_option():
    from lorcana.coach.openai_analyzer import OUTPUT_SCHEMA
    properties = OUTPUT_SCHEMA["properties"]["findings"]["items"]["properties"]
    assert "confidence" not in properties
    assert properties["claim_type"]["enum"] == ["inference"]

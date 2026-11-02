from types import SimpleNamespace

import pytest

from app.advisor import MODEL, AdvisorError, explain

PLAN = {
    "inputs": {"crop_name": "Wheat (spring)"},
    "summary": {"irrigation_events": [{"date": "2026-11-07", "gross_mm": 189.1}]},
    "balance_start": "2026-10-19",
    "days": [{"date": "2026-11-07", "etc": 6.3, "depletion": 0.0, "depletion_before_irrigation": 113.4}],
    "climate": None,
    "warnings": ["No last watering date was given."],
}


class FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(response):
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_explain_sends_plan_and_language_and_returns_text():
    response = SimpleNamespace(stop_reason="end_turn", model=MODEL,
                               content=[SimpleNamespace(type="text", text="This week:\n- Water on Saturday.")])
    client, messages = fake_client(response)
    result = explain(PLAN, "am", client=client)
    assert result == {"text": "This week:\n- Water on Saturday.", "model": MODEL, "language": "Amharic"}
    sent = messages.kwargs
    assert sent["model"] == MODEL
    assert sent["fallbacks"] == "default"
    prompt = sent["messages"][0]["content"]
    assert "Amharic" in prompt and "189.1" in prompt and "No last watering date" in prompt
    assert "depletion_before_irrigation" not in prompt  # chart-only fields are left out


def test_refusal_is_reported_not_shown_as_advice():
    client, _ = fake_client(SimpleNamespace(stop_reason="refusal", model=MODEL, content=[]))
    with pytest.raises(AdvisorError, match="declined"):
        explain(PLAN, client=client)


def test_unknown_language_falls_back_to_english():
    response = SimpleNamespace(stop_reason="end_turn", model=MODEL, content=[SimpleNamespace(type="text", text="ok")])
    client, messages = fake_client(response)
    assert explain(PLAN, "xx", client=client)["language"] == "English"

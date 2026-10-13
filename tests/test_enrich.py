from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic")

from video_ingest.enrich import Sources, build_user_message, clean_category, clean_tag  # noqa: E402
from video_ingest.enrich_claude import FALLBACK_BETA, ClaudeEnricher, Enrichment  # noqa: E402

SOURCES = Sources(
    title="Smoothie Bowl",
    platform="tiktok",
    author="chef",
    caption="had to bring this back #fyp",
    on_screen_text="2 FROZEN BANANAS\n34CUPICE",
)
PARSED = Enrichment(
    summary="  A thick   chocolate smoothie bowl. ",
    key_points=["- 2 frozen bananas", "3/4 cup ice", "  "],
    categories=["[[cooking]]", "Desserts"],
    tags=["#Smoothie Bowl", "high-protein", "High Protein"],
)


class FakeMessages:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response, exc, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.response


def enricher(model="claude-opus-5-5", **resp):
    response = SimpleNamespace(
        **{"stop_reason": "end_turn", "parsed_output": PARSED, "model": model, **resp}
    )
    messages = FakeMessages(response)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return ClaudeEnricher(model=model, client=client), messages


def test_build_user_message_marks_empty_sources():
    msg = build_user_message(SOURCES, ["Cooking"], [])
    assert "<transcript>\n(none)\n</transcript>" in msg
    assert "<on_screen_text>\n2 FROZEN BANANAS\n34CUPICE\n</on_screen_text>" in msg
    assert "<known_categories>\nCooking\n</known_categories>" in msg


@pytest.mark.parametrize(
    ("raw", "clean"), [("#Meal Prep", "meal-prep"), ("air_fryer!", "air-fryer"), ("--x--", "x")]
)
def test_clean_tag(raw, clean):
    assert clean_tag(raw) == clean


def test_clean_category_snaps_to_known_spelling():
    assert clean_category("[[self help]]", ["Self Help", "Gym"]) == "Self Help"
    assert clean_category("Desserts", ["Cooking"]) == "Desserts"


def test_enrich_success_cleans_output_and_sends_request():
    e, messages = enricher()
    result = e.enrich(SOURCES, ["Cooking"], ["smoothie-bowl"])
    assert result.ok
    assert result.summary == "A thick chocolate smoothie bowl."
    assert result.key_points == ["2 frozen bananas", "3/4 cup ice"]
    assert result.categories == ["Cooking", "Desserts"]
    assert result.tags == ["smoothie-bowl", "high-protein"]

    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is Enrichment
    assert call["output_config"] == {"effort": "low"}
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert "34CUPICE" in call["messages"][0]["content"]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_no_fallback_params_for_models_without_default_fallback():
    e, messages = enricher(model="claude-haiku-5-5")
    e.enrich(SOURCES, [], [])
    assert "fallbacks" not in messages.calls[0]


def test_reports_model_that_answered_after_fallback():
    e, _ = enricher(model="claude-opus-5-5")
    e.client.beta.messages.response.model = "claude-opus-4-8"
    assert e.enrich(SOURCES, [], []).model == "claude-opus-4-8"


@pytest.mark.parametrize(
    ("resp", "error"),
    [
        ({"stop_reason": "refusal"}, "refused by model"),
        ({"stop_reason": "max_tokens"}, "no parsable output (max_tokens)"),
        ({"parsed_output": None}, "no parsable output (end_turn)"),
    ],
)
def test_unusable_responses_fail(resp, error):
    e, _ = enricher(**resp)
    result = e.enrich(SOURCES, [], [])
    assert not result.ok
    assert result.error == error


def test_api_errors_fail_without_raising():
    client = SimpleNamespace(
        beta=SimpleNamespace(messages=FakeMessages(exc=ConnectionError("network down")))
    )
    result = ClaudeEnricher(client=client).enrich(SOURCES, [], [])
    assert not result.ok
    assert result.error == "ConnectionError: network down"


def test_fatal_errors_propagate():
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx2.Response(401, request=request), body=None
    )
    client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(exc=exc)))
    with pytest.raises(anthropic.AuthenticationError):
        ClaudeEnricher(client=client).enrich(SOURCES, [], [])

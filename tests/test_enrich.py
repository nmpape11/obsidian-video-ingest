from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic")

from video_ingest.enrich import (  # noqa: E402
    Sources,
    build_user_message,
    clean_category,
    clean_tag,
    to_result,
)
from video_ingest.enrich_claude import (  # noqa: E402
    FALLBACK_BETA,
    ClaudeEnricher,
    Enrichment,
    schema_for,
)

CATEGORIES = ["Cooking", "Gym", "Self Help", "Other"]

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
    tags=["#Smoothie Bowl", "high-protein", "High Protein", "#fyp", "#ForYouPage"],
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
    msg = build_user_message(SOURCES, ["Cooking", "Other"], [])
    assert "<transcript>\n(none)\n</transcript>" in msg
    assert "<on_screen_text>\n2 FROZEN BANANAS\n34CUPICE\n</on_screen_text>" in msg
    assert "<allowed_categories>\nCooking, Other\n</allowed_categories>" in msg


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("#Meal Prep", "meal-prep"),
        ("air_fryer!", "air-fryer"),
        ("--x--", "x"),
        ("#fyp", ""),
        ("#ForYou-Page", ""),
        ("viral", ""),
    ],
)
def test_clean_tag(raw, clean):
    assert clean_tag(raw) == clean


def test_clean_category_only_allows_listed_names():
    assert clean_category("[[self help]]", CATEGORIES) == "Self Help"
    assert clean_category("Desserts", CATEGORIES) is None


def test_to_result_falls_back_to_other_and_caps_categories():
    r = to_result("s", [], ["Desserts"], [], CATEGORIES, "m")
    assert r.categories == ["Other"]
    r = to_result("s", [], ["Gym", "Cooking", "Self Help"], [], CATEGORIES, "m")
    assert r.categories == ["Gym", "Cooking"]
    assert to_result("s", [], [], [], ["Cooking"], "m").categories == []


def test_schema_restricts_categories_to_enum():
    schema = schema_for(tuple(CATEGORIES)).model_json_schema()
    items = schema["properties"]["categories"]["items"]
    assert items["enum"] == CATEGORIES
    assert set(schema["required"]) == {"summary", "key_points", "categories", "tags"}


def test_enrich_success_cleans_output_and_sends_request():
    e, messages = enricher()
    result = e.enrich(SOURCES, CATEGORIES, ["smoothie-bowl"])
    assert result.ok
    assert result.summary == "A thick chocolate smoothie bowl."
    assert result.key_points == ["2 frozen bananas", "3/4 cup ice"]
    assert result.categories == ["Cooking"]  # "Desserts" isn't an allowed category
    assert result.tags == ["smoothie-bowl", "high-protein"]  # fyp/foryoupage dropped

    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is schema_for(tuple(CATEGORIES))
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

import pytest

from video_ingest.fetch import clean_caption, pick_subtitles, short_error, vtt_to_text

VTT = """WEBVTT
Kind: captions
Language: en

1
00:00:00.000 --> 00:00:02.000
<c>Hello</c> there

2
00:00:01.500 --> 00:00:03.000
Hello there

00:00:03.000 --> 00:00:05.000 align:start
general Kenobi
"""


def test_vtt_to_text_strips_markup_and_rolling_repeats():
    assert vtt_to_text(VTT) == "Hello there general Kenobi"


def test_clean_caption_restores_flattened_lines():
    raw = "Quesadillas 🧀  Macros:  - 450 Calories  - 70g Protein  "
    assert clean_caption(raw) == "Quesadillas 🧀\nMacros:\n- 450 Calories\n- 70g Protein"


def test_clean_caption_keeps_real_newlines():
    assert clean_caption("line one\nline two") == "line one\nline two"


def sub(ext, url="u"):
    return {"ext": ext, "url": url}


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        ({}, None),
        ({"subtitles": {"en": [sub("json3"), sub("vtt", "en-vtt")]}}, "en-vtt"),
        (
            {
                "subtitles": {"de": [sub("vtt", "de")]},
                "automatic_captions": {"en": [sub("vtt", "auto-en")]},
            },
            "de",  # manual subs beat automatic, even in another language
        ),
        ({"subtitles": {"fr": [sub("vtt", "fr")], "en": [sub("vtt", "en")]}}, "en"),
        ({"subtitles": {"en": [sub("srt")]}}, None),
    ],
)
def test_pick_subtitles(info, expected):
    picked = pick_subtitles(info)
    assert (picked or {}).get("url") == expected


def test_short_error_strips_prefix_colour_and_extra_lines():
    exc = Exception("\x1b[0;31mERROR:\x1b[0m [TikTok] 1: Blocked\nTraceback ...")
    assert short_error(exc) == "[TikTok] 1: Blocked"
    assert short_error(ValueError()) == "ValueError"

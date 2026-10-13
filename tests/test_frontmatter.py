from datetime import date

import pytest

from video_ingest.frontmatter import FrontmatterError, get, get_list, render, set_fields, split

NOTE = """---
url: https://tiktok.com/@a/video/1
source_title: "Pasta: hack?"
category:
  - "[[Cooking]]"
tags: [a, b]
processed: false
---

## Summary
"""


def test_split():
    fm, body = split(NOTE)
    assert fm[0] == "url: https://tiktok.com/@a/video/1"
    assert body == "\n## Summary\n"


@pytest.mark.parametrize("text", ["no frontmatter\n", "---\nurl: x\n"])
def test_split_rejects(text):
    with pytest.raises(FrontmatterError):
        split(text)


def test_get():
    assert get(NOTE, "url") == "https://tiktok.com/@a/video/1"
    assert get(NOTE, "source_title") == "Pasta: hack?"
    assert get(NOTE, "processed") == "false"
    assert get(NOTE, "missing") is None
    assert get(NOTE, "category") is None  # block list, not a scalar


def test_set_fields_replaces_appends_and_preserves():
    out = set_fields(NOTE, {"processed": True, "fetched": date(2026, 1, 2), "duration": 64})
    assert "processed: true\n" in out
    assert out.count("processed:") == 1
    assert 'category:\n  - "[[Cooking]]"\ntags: [a, b]\n' in out
    assert out.endswith("duration: 64\n---\n\n## Summary\n")
    assert "fetched: 2026-01-02\n" in out


def test_set_fields_quotes_strings():
    out = set_fields(NOTE, {"author": 'He said "hi": ok'})
    assert get(out, "author") == 'He said "hi": ok'


def test_set_fields_none_removes_key_and_its_list():
    out = set_fields(NOTE, {"category": None})
    assert "category" not in out
    assert "[[Cooking]]" not in out
    assert "tags: [a, b]" in out


def test_set_fields_is_idempotent():
    fields = {"fetch_status": "ok", "fetch_error": None}
    once = set_fields(NOTE, fields)
    assert set_fields(once, fields) == once


@pytest.mark.parametrize(
    ("value", "rendered"),
    [
        ("ok", "ok"),
        ("to-try", "to-try"),
        ("user.name_1", "user.name_1"),
        ("true", '"true"'),
        ("No", '"No"'),
        ("123abc", '"123abc"'),
        ("two words", '"two words"'),
        ("", '""'),
    ],
)
def test_render_quotes_only_when_needed(value, rendered):
    assert render(value) == rendered


def test_get_list_block_and_flow_styles():
    assert get_list(NOTE, "category") == ["[[Cooking]]"]
    assert get_list(NOTE, "tags") == ["a", "b"]
    assert get_list(NOTE, "url") == ["https://tiktok.com/@a/video/1"]
    assert get_list(NOTE, "missing") == []


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("tags: []", []),
        (
            "tags: [\"high-protein\", 'meal prep', air-fryer]",
            ["high-protein", "meal prep", "air-fryer"],
        ),
        ('category: ["[[Self Help]]", "[[Gym]]"]', ["[[Self Help]]", "[[Gym]]"]),
    ],
)
def test_get_list_flow_variants(line, expected):
    key = line.split(":")[0]
    assert get_list(f"---\n{line}\n---\n", key) == expected


def test_set_fields_writes_block_lists_and_replaces_old_list():
    out = set_fields(NOTE, {"category": ["[[Cooking]]", "[[Gym]]"], "tags": ["high-protein"]})
    assert 'category:\n  - "[[Cooking]]"\n  - "[[Gym]]"\ntags:\n  - high-protein\nprocessed' in out
    assert get_list(out, "category") == ["[[Cooking]]", "[[Gym]]"]
    assert set_fields(out, {"tags": []}).count("tags: []") == 1

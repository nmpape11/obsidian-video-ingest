from datetime import date

from video_ingest import frontmatter
from video_ingest.enrich import EnrichResult
from video_ingest.notes import fill_section, note_categories, note_sources, with_enrichment

NOTE = """---
url: https://tiktok.com/@x/video/1
platform: tiktok
source_title: "Smoothie Bowl"
category: []
tags: [smoothie]
processed: false
author: chef
---

## Summary


## Key points

- 

## Source

> [!info]- Caption
> had to bring this back

> [!abstract]- On-screen text (frames)
> - 2 FROZEN BANANAS
> - 34CUPICE
"""
RESULT = EnrichResult(
    ok=True,
    summary="A chocolate smoothie bowl.",
    key_points=["2 frozen bananas", "3/4 cup ice"],
    categories=["Cooking"],
    tags=["smoothie", "dessert"],
    model="claude-opus-5-5",
)


def test_note_sources_reads_callouts():
    src = note_sources(NOTE, "file name")
    assert src.title == "Smoothie Bowl"
    assert src.author == "chef"
    assert src.caption == "had to bring this back"
    assert src.transcript == ""
    assert src.on_screen_text == "2 FROZEN BANANAS\n34CUPICE"


def test_fill_section_replaces_placeholder_only():
    text, filled = fill_section(NOTE, "## Key points", "- a\n- b")
    assert filled
    assert "## Key points\n\n- a\n- b\n\n## Source" in text
    again, filled = fill_section(text, "## Key points", "- c")
    assert not filled and again == text
    assert fill_section(NOTE, "## Missing", "x") == (NOTE, False)


def test_with_enrichment_fills_note_and_marks_processed():
    out, kept = with_enrichment(NOTE, RESULT, date(2026, 10, 12))
    assert kept == []
    assert "## Summary\n\nA chocolate smoothie bowl.\n\n## Key points" in out
    assert "## Key points\n\n- 2 frozen bananas\n- 3/4 cup ice\n\n## Source" in out
    assert frontmatter.get_list(out, "category") == ["[[Cooking]]"]
    assert frontmatter.get_list(out, "tags") == ["smoothie", "dessert"]
    assert frontmatter.get(out, "processed") == "true"
    assert frontmatter.get(out, "enrich_model") == "claude-opus-5-5"
    assert "> - 34CUPICE" in out  # sources untouched


def test_with_enrichment_keeps_user_content_and_merges_lists():
    text = NOTE.replace("## Summary\n\n", "## Summary\n\nMy own words.\n").replace(
        "category: []", 'category:\n  - "[[Desserts]]"'
    )
    out, kept = with_enrichment(text, RESULT, date(2026, 10, 12))
    assert kept == ["## Summary"]
    assert "My own words." in out and "A chocolate smoothie bowl." not in out
    assert note_categories(out) == ["Desserts", "Cooking"]


def test_with_enrichment_failure_then_success():
    failed, _ = with_enrichment(NOTE, EnrichResult(ok=False, error="refused"), date(2026, 1, 1))
    assert frontmatter.get(failed, "enrich_status") == "failed"
    assert frontmatter.get(failed, "processed") == "false"
    ok, _ = with_enrichment(failed, RESULT, date(2026, 1, 2))
    assert frontmatter.get(ok, "enrich_status") is None
    assert frontmatter.get(ok, "enrich_error") is None

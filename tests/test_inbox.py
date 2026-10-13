import pytest

from video_ingest.inbox import (
    detect_platform,
    fetchable_url,
    normalize_url,
    parse_inbox,
    parse_line,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.tiktok.com/@a/video/1?is_from_webapp=1", "https://tiktok.com/@a/video/1"),
        ("https://tiktok.com/@a/video/1/", "https://tiktok.com/@a/video/1"),
        ("http://m.instagram.com/reel/X/?igsh=y#frag", "https://instagram.com/reel/X"),
        ("https://vm.tiktok.com/ZM1/.", "https://vm.tiktok.com/ZM1"),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_detect_platform():
    assert detect_platform("https://vt.tiktok.com/x") == "tiktok"
    assert detect_platform("https://instagr.am/p/x") == "instagram"
    assert detect_platform("https://youtube.com/watch?v=1") is None


@pytest.mark.parametrize(
    ("line", "title"),
    [
        ("- Best cue https://tiktok.com/@a/video/1", "Best cue"),
        ("[Pasta hack](https://instagram.com/reel/X/)", "Pasta hack"),
        ("https://tiktok.com/@a/video/1 - after the url", "after the url"),
        ("- [ ] Title: https://instagram.com/p/X/", "Title"),
        ("https://tiktok.com/@a/video/1", ""),
    ],
)
def test_parse_line_titles(line, title):
    entry = parse_line(line)
    assert entry is not None
    assert entry.title == title


@pytest.mark.parametrize(
    "line",
    [
        "https://example.com/x",
        "two https://tiktok.com/a https://tiktok.com/b",
        "no url here",
    ],
)
def test_parse_line_rejects(line):
    assert parse_line(line) is None


def test_parse_inbox_keeps_non_entries():
    text = "# Heading\n\n- a https://tiktok.com/@a/video/1\nnote https://example.com\n"
    entries, kept = parse_inbox(text)
    assert [e.url for e in entries] == ["https://tiktok.com/@a/video/1"]
    assert kept == ["# Heading", "", "note https://example.com"]


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("https://tiktok.com/@a/video/1", "https://www.tiktok.com/@a/video/1"),
        ("https://instagram.com/reel/X", "https://www.instagram.com/reel/X"),
        ("https://vm.tiktok.com/ZM1", "https://vm.tiktok.com/ZM1"),
    ],
)
def test_fetchable_url(stored, expected):
    assert fetchable_url(stored) == expected

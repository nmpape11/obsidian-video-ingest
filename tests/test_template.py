import re
from datetime import date
from pathlib import Path

from video_ingest.inbox import Entry
from video_ingest.notes import render_note

TEMPLATE = Path(__file__).parents[1] / "templates" / "Video.md"
KEY_RE = re.compile(r"^(\w+):", re.MULTILINE)


def keys(text: str) -> list[str]:
    return KEY_RE.findall(text.split("---")[1])


def test_template_matches_pipeline_schema():
    entry = Entry(url="https://tiktok.com/x", platform="tiktok", title="t", raw="")
    assert keys(TEMPLATE.read_text()) == keys(render_note(entry, date(2026, 1, 1)))

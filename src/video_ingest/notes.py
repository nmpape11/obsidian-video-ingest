"""Render, name and write one Obsidian note per video."""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import frontmatter
from .enrich import EnrichResult, Sources
from .fetch import FetchResult
from .inbox import Entry, normalize_url, parse_inbox
from .ocr import OcrResult

MAX_NAME_LEN = 80
ILLEGAL_CHARS_RE = re.compile(r'[\\/:*?"<>|#^\[\]]')
FRONTMATTER_URL_RE = re.compile(r"^url:\s*[\"']?(\S+?)[\"']?\s*$", re.MULTILINE)


def safe_filename(title: str) -> str:
    """Strip emoji, symbols and characters Obsidian/filesystems reject."""
    spaced = ILLEGAL_CHARS_RE.sub(" ", title)
    name = "".join(ch for ch in spaced if unicodedata.category(ch)[0] in "LNZP" or ch in "-_'&+,")
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > MAX_NAME_LEN:
        name = name[:MAX_NAME_LEN].rsplit(" ", 1)[0].strip(" .")
    return name


def fallback_name(entry: Entry) -> str:
    slug = entry.url.rstrip("/").rsplit("/", 1)[-1]
    return safe_filename(f"{entry.platform} {slug}") or entry.platform


def yaml_str(value: str) -> str:
    # JSON strings are valid YAML double-quoted scalars.
    return json.dumps(value, ensure_ascii=False)


def render_note(entry: Entry, created: date) -> str:
    return (
        "---\n"
        f"url: {entry.url}\n"
        f"platform: {entry.platform}\n"
        f"source_title: {yaml_str(entry.title)}\n"
        f"created: {created.isoformat()}\n"
        "category: []\n"
        "tags: []\n"
        "status: to-try\n"
        "processed: false\n"
        "---\n"
        "\n"
        "## Summary\n"
        "\n"
        "\n"
        "## Key points\n"
        "\n"
        "- \n"
    )


def existing_urls(out_dir: Path) -> set[str]:
    urls: set[str] = set()
    if not out_dir.is_dir():
        return urls
    for note in out_dir.rglob("*.md"):
        text = note.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            continue
        frontmatter = text.split("---", 2)[1] if text.count("---") >= 2 else ""
        match = FRONTMATTER_URL_RE.search(frontmatter)
        if match:
            urls.add(normalize_url(match.group(1)))
    return urls


@dataclass
class Plan:
    to_create: list[tuple[Path, Entry]] = field(default_factory=list)
    duplicates: list[Entry] = field(default_factory=list)
    kept_lines: list[str] = field(default_factory=list)


def plan_ingest(inbox_text: str, out_dir: Path) -> Plan:
    entries, kept = parse_inbox(inbox_text)
    plan = Plan(kept_lines=kept)
    seen = existing_urls(out_dir)
    taken = {p.stem.lower() for p in out_dir.glob("*.md")} if out_dir.is_dir() else set()

    for entry in entries:
        if entry.url in seen:
            plan.duplicates.append(entry)
            continue
        seen.add(entry.url)

        base = safe_filename(entry.title) or fallback_name(entry)
        name, n = base, 2
        while name.lower() in taken:
            name, n = f"{base} {n}", n + 1
        taken.add(name.lower())
        plan.to_create.append((out_dir / f"{name}.md", entry))
    return plan


def apply_plan(plan: Plan, inbox_path: Path, created: date) -> None:
    """Write notes, back up the inbox, then rewrite it with only the kept lines."""
    for path, entry in plan.to_create:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as fh:  # never overwrite
            fh.write(render_note(entry, created))

    shutil.copy2(inbox_path, inbox_path.with_name(inbox_path.name + ".bak"))
    remaining = "\n".join(plan.kept_lines).strip("\n")
    inbox_path.write_text(remaining + "\n" if remaining else "", encoding="utf-8")


SOURCE_HEADING = "## Source"
TRANSCRIPT_TITLE = "Transcript"
OCR_TITLE = "On-screen text"
CAPTION_TITLE = "Caption"
SUMMARY_HEADING = "## Summary"
KEY_POINTS_HEADING = "## Key points"
PLACEHOLDER_RE = re.compile(r"^\s*(?:[-*]\s*)?$")
WIKILINK_RE = re.compile(r"^\[\[(.+?)\]\]$")


def callout(kind: str, title: str, text: str) -> str:
    """Foldable Obsidian callout; collapsed so long transcripts don't bury the summary."""
    lines = [f"> [!{kind}]- {title}"]
    lines += [f"> {line}" if line else ">" for line in text.splitlines()]
    return "\n".join(lines)


def with_fetch_result(text: str, result: FetchResult, fetched: date) -> str:
    """Record a fetch in the note: frontmatter fields, plus a Source section on success."""
    if not result.ok:
        return frontmatter.set_fields(
            text, {"fetch_status": "failed", "fetched": fetched, "fetch_error": result.error}
        )

    text = frontmatter.set_fields(
        text,
        {
            "author": result.author or None,
            "duration": result.duration,
            "uploaded": result.uploaded,
            "transcript_source": result.transcript_source,
            "fetch_status": "ok",
            "fetched": fetched,
            "fetch_error": None,
        },
    )
    if f"\n{SOURCE_HEADING}\n" in text:
        return text

    blocks = []
    if result.caption:
        blocks.append(callout("info", CAPTION_TITLE, result.caption))
    if result.transcript:
        blocks.append(
            callout("quote", f"{TRANSCRIPT_TITLE} ({result.transcript_source})", result.transcript)
        )
    if not blocks:
        return text
    return text.rstrip("\n") + f"\n\n{SOURCE_HEADING}\n\n" + "\n\n".join(blocks) + "\n"


def callout_text(text: str, title: str) -> str:
    """Body of the first callout whose title starts with `title`, or ""."""
    head = re.compile(rf"^> \[!\w+\][-+]? {re.escape(title)}\b")
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if head.match(line):
            body = []
            for ln in lines[i + 1 :]:
                if not ln.startswith(">"):
                    break
                body.append(ln[2:] if ln.startswith("> ") else ln[1:])
            return "\n".join(body).strip()
    return ""


def append_to_section(text: str, heading: str, block: str) -> str:
    """Add block at the end of the `heading` section, creating the section if missing."""
    lines = text.rstrip("\n").split("\n")
    if heading not in lines:
        return "\n".join(lines) + f"\n\n{heading}\n\n{block}\n"
    start = lines.index(heading)
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"#{1,2} ", lines[i])), len(lines)
    )
    body_end = end
    while body_end > start + 1 and not lines[body_end - 1].strip():
        body_end -= 1
    rest = lines[end:]
    out = lines[:body_end] + ["", *block.split("\n")] + ([""] + rest if rest else [])
    return "\n".join(out) + "\n"


def with_ocr_result(text: str, result: OcrResult) -> str:
    """Record OCR in the note: frontmatter fields, plus an on-screen text callout."""
    if not result.ok:
        return frontmatter.set_fields(text, {"ocr_status": "failed", "ocr_error": result.error})
    text = frontmatter.set_fields(
        text, {"ocr_status": "ok", "ocr_source": result.source, "ocr_error": None}
    )
    if not result.lines or callout_text(text, OCR_TITLE):
        return text
    body = "\n".join(f"- {line}" for line in result.lines)
    return append_to_section(
        text, SOURCE_HEADING, callout("abstract", f"{OCR_TITLE} ({result.source})", body)
    )


def fill_section(text: str, heading: str, content: str) -> tuple[str, bool]:
    """Put content under `heading` if the section is empty or only a "- " placeholder.

    Returns (text, filled). Never overwrites what someone wrote there.
    """
    lines = text.rstrip("\n").split("\n")
    if heading not in lines:
        return text, False
    start = lines.index(heading)
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"#{1,2} ", lines[i])), len(lines)
    )
    if not all(PLACEHOLDER_RE.match(line) for line in lines[start + 1 : end]):
        return text, False
    rest = lines[end:]
    out = lines[: start + 1] + ["", *content.split("\n")] + ([""] + rest if rest else [])
    return "\n".join(out) + "\n", True


def note_sources(text: str, title: str) -> Sources:
    return Sources(
        title=frontmatter.get(text, "source_title") or title,
        platform=frontmatter.get(text, "platform") or "",
        author=frontmatter.get(text, "author") or "",
        caption=callout_text(text, CAPTION_TITLE),
        transcript=callout_text(text, TRANSCRIPT_TITLE),
        on_screen_text="\n".join(
            line.removeprefix("- ") for line in callout_text(text, OCR_TITLE).split("\n")
        ).strip(),
    )


def note_categories(text: str) -> list[str]:
    """Category names from "[[Name]]" (or bare) entries in the category list."""
    names = []
    for item in frontmatter.get_list(text, "category"):
        m = WIKILINK_RE.match(item.strip())
        names.append(m.group(1) if m else item.strip())
    return [n for n in names if n]


def merge(existing: list[str], new: list[str]) -> list[str]:
    seen = {x.lower() for x in existing}
    return existing + [x for x in new if x.lower() not in seen and not seen.add(x.lower())]


def with_enrichment(text: str, result: EnrichResult, enriched: date) -> tuple[str, list[str]]:
    """Record an enrichment. Returns (text, sections left alone because they had content)."""
    if not result.ok:
        fields = {"enrich_status": "failed", "enrich_error": result.error}
        return frontmatter.set_fields(text, fields), []

    categories = merge(note_categories(text), result.categories)
    text = frontmatter.set_fields(
        text,
        {
            "category": [f"[[{c}]]" for c in categories],
            "tags": merge(frontmatter.get_list(text, "tags"), result.tags),
            "processed": True,
            "enriched": enriched,
            "enrich_model": result.model or None,
            "enrich_status": None,
            "enrich_error": None,
        },
    )
    kept = []
    text, filled = fill_section(text, SUMMARY_HEADING, result.summary)
    if not filled:
        kept.append(SUMMARY_HEADING)
    if result.key_points:
        points = "\n".join(f"- {p}" for p in result.key_points)
        text, filled = fill_section(text, KEY_POINTS_HEADING, points)
        if not filled:
            kept.append(KEY_POINTS_HEADING)
    return text, kept

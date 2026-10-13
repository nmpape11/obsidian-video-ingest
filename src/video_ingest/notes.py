"""Render, name and write one Obsidian note per video."""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .inbox import Entry, normalize_url, parse_inbox

MAX_NAME_LEN = 80
ILLEGAL_CHARS_RE = re.compile(r'[\\/:*?"<>|#^\[\]]')
FRONTMATTER_URL_RE = re.compile(r"^url:\s*[\"']?(\S+?)[\"']?\s*$", re.MULTILINE)


def safe_filename(title: str) -> str:
    """Strip emoji, symbols and characters Obsidian/filesystems reject."""
    kept = "".join(
        ch for ch in title
        if unicodedata.category(ch)[0] in "LNZP" or ch in "-_'&+,"
    )
    name = ILLEGAL_CHARS_RE.sub(" ", kept)
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

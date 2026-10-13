"""Minimal line-based frontmatter editing.

Only touches the keys being set, so whatever Obsidian or the user wrote elsewhere in the
frontmatter (lists, comments, key order) is preserved byte for byte.
"""

from __future__ import annotations

import json
import re
from datetime import date

KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")
# Identifier-like strings ("ok", "to-try", "fairfiteats") are written unquoted, matching
# how Obsidian's Properties panel writes them.
BARE_RE = re.compile(r"^[A-Za-z_][\w.-]*$")
YAML_KEYWORDS = {"true", "false", "yes", "no", "on", "off", "null", "y", "n"}

Scalar = str | int | float | bool | date | None
Value = Scalar | list[str]
FLOW_ITEM_RE = re.compile(r'\s*("(?:[^"\\]|\\.)*"|\'[^\']*\'|[^,]+?)\s*(?:,|$)')
BLOCK_ITEM_RE = re.compile(r"^\s*-\s?(.*)$")


class FrontmatterError(ValueError):
    pass


def split(text: str) -> tuple[list[str], str]:
    """Return (frontmatter lines, body). Raises if the note has no frontmatter."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("note has no frontmatter")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1 :])
    raise FrontmatterError("unterminated frontmatter")


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return json.loads(value) if value[0] == '"' else value[1:-1]
    return value


def get(text: str, key: str) -> str | None:
    """Raw value of a top-level scalar key, unquoted. None if absent or empty."""
    fm, _ = split(text)
    for line in fm:
        m = KEY_RE.match(line)
        if m and m.group(1) == key:
            return unquote(m.group(2)) or None
    return None


def get_list(text: str, key: str) -> list[str]:
    """Items of a list key in flow ([a, "b"]) or block ("- a") style; a scalar is one item."""
    fm, _ = split(text)
    for i, line in enumerate(fm):
        m = KEY_RE.match(line)
        if not (m and m.group(1) == key):
            continue
        value = m.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            return [unquote(x) for x in FLOW_ITEM_RE.findall(inner) if unquote(x)]
        if value:
            return [unquote(value)]
        items = []
        for nxt in fm[i + 1 :]:
            item = BLOCK_ITEM_RE.match(nxt)
            if not item:
                break
            if unquote(item.group(1)):
                items.append(unquote(item.group(1)))
        return items
    return []


def render(value: Scalar) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    if BARE_RE.match(text) and text.lower() not in YAML_KEYWORDS:
        return text
    # JSON strings are valid YAML double-quoted scalars.
    return json.dumps(text, ensure_ascii=False)


def entry(key: str, value: Value) -> list[str]:
    """Frontmatter lines for one key. Lists use block style, as Obsidian writes them."""
    if isinstance(value, list):
        return [f"{key}: []"] if not value else [f"{key}:", *(f"  - {render(v)}" for v in value)]
    return [f"{key}: {render(value)}"]


def set_fields(text: str, fields: dict[str, Value]) -> str:
    """Set or replace top-level keys; a value of None removes the key.

    A replaced key's continuation lines (indented or "- " list items) are dropped with it.
    New keys are appended at the end of the frontmatter in the given order.
    """
    fm, body = split(text)
    out: list[str] = []
    done: set[str] = set()
    skipping = False
    for line in fm:
        m = KEY_RE.match(line)
        if m:
            skipping = False
            key = m.group(1)
            if key in fields:
                skipping = True
                done.add(key)
                if fields[key] is not None:
                    out.extend(entry(key, fields[key]))
                continue
        elif skipping and (line.startswith((" ", "\t", "-")) or not line.strip()):
            continue
        else:
            skipping = False
        out.append(line)
    for key, value in fields.items():
        if key not in done and value is not None:
            out.extend(entry(key, value))
    return "\n".join(["---", *out, "---"]) + "\n" + body

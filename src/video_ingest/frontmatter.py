"""Minimal line-based frontmatter editing.

Only touches the keys being set, so whatever Obsidian or the user wrote elsewhere in the
frontmatter (lists, comments, key order) is preserved byte for byte.
"""

from __future__ import annotations

import json
import re
from datetime import date

KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")

Scalar = str | int | float | bool | date | None


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


def get(text: str, key: str) -> str | None:
    """Raw value of a top-level scalar key, unquoted. None if absent or empty."""
    fm, _ = split(text)
    for line in fm:
        m = KEY_RE.match(line)
        if m and m.group(1) == key:
            value = m.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = json.loads(value) if value[0] == '"' else value[1:-1]
            return value or None
    return None


def render(value: Scalar) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    # JSON strings are valid YAML double-quoted scalars.
    return json.dumps(str(value), ensure_ascii=False)


def set_fields(text: str, fields: dict[str, Scalar]) -> str:
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
                    out.append(f"{key}: {render(fields[key])}")
                continue
        elif skipping and (line.startswith((" ", "\t", "-")) or not line.strip()):
            continue
        else:
            skipping = False
        out.append(line)
    for key, value in fields.items():
        if key not in done and value is not None:
            out.append(f"{key}: {render(value)}")
    return "\n".join(["---", *out, "---"]) + "\n" + body

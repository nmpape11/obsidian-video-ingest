"""Shared helpers for stages that walk and rewrite notes in the vault."""

from __future__ import annotations

import os
from pathlib import Path

from . import frontmatter
from .config import Config


class VaultError(ValueError):
    pass


def notes_dir(cli_vault: Path | None, cli_out: str | None, cfg: Config) -> Path:
    """Resolve the notes folder from CLI flags, falling back to config."""
    vault = cli_vault or cfg.vault
    if vault is None:
        raise VaultError("no vault given (use --vault or set 'vault' in config)")
    out_dir = vault.expanduser() / (cli_out or cfg.out)
    if not out_dir.is_dir():
        raise VaultError(f"notes folder not found: {out_dir}")
    return out_dir


def pending_notes(
    out_dir: Path,
    status_key: str,
    retry_failed: bool,
    require: dict[str, str | set[str]] | None = None,
) -> list[Path]:
    """Notes with a url whose status_key is unset (or "failed", when retrying).

    require: other frontmatter values a note must have, e.g. {"fetch_status": "ok"};
    a set allows any of its values.
    Hidden folders (.trash, .obsidian) are skipped. Sorted by path.
    """
    todo = []
    for path in sorted(out_dir.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(out_dir).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            url = frontmatter.get(text, "url")
            status = frontmatter.get(text, status_key)
            ok = all(
                frontmatter.get(text, k) in (v if isinstance(v, set) else {v})
                for k, v in (require or {}).items()
            )
        except (frontmatter.FrontmatterError, UnicodeDecodeError):
            continue
        if url and ok and (status is None or (retry_failed and status == "failed")):
            todo.append(path)
    return todo


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

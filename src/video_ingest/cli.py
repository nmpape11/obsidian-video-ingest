"""Command-line entry point: video-ingest."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .config import ConfigError, load_config
from .notes import apply_plan, plan_ingest


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-ingest",
        description="Create one Obsidian note per TikTok/Instagram link in an inbox note.",
    )
    p.add_argument("--config", type=Path, help="TOML config (default: ./config.toml if present)")
    p.add_argument("--vault", type=Path, help="vault root directory")
    p.add_argument(
        "--inbox",
        action="append",
        help="inbox note relative to vault; repeatable (overrides config 'inboxes')",
    )
    p.add_argument("--out", help="notes folder relative to vault")
    p.add_argument("--apply", action="store_true", help="write changes (default: preview)")
    return p


def ingest_one(vault: Path, inbox: Path, out_dir: Path, apply: bool) -> int:
    print(f"== {inbox.relative_to(vault)}")
    if not inbox.is_file():
        print(f"error: inbox not found: {inbox}", file=sys.stderr)
        return 2

    plan = plan_ingest(inbox.read_text(encoding="utf-8"), out_dir)
    unparsed = [line for line in plan.kept_lines if "http" in line]

    for path, entry in plan.to_create:
        print(f"+ {path.relative_to(vault)}  <- {entry.url}")
    for entry in plan.duplicates:
        print(f"= duplicate, skipped: {entry.url}")
    for line in unparsed:
        print(f"? unparsed, left in inbox: {line.strip()}")
    print(f"{len(plan.to_create)} new, {len(plan.duplicates)} duplicate, {len(unparsed)} unparsed")

    if not apply:
        return 0
    if not plan.to_create and not plan.duplicates:
        print("nothing to do")
        return 0
    apply_plan(plan, inbox, date.today())
    print(f"wrote {len(plan.to_create)} notes; inbox backed up to {inbox.name}.bak")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    vault = args.vault or cfg.vault
    if vault is None:
        print("error: no vault given (use --vault or set 'vault' in config)", file=sys.stderr)
        return 2
    vault = vault.expanduser()
    out_dir = vault / (args.out or cfg.out)
    inboxes = args.inbox or cfg.inboxes

    status = 0
    for name in inboxes:
        # Inboxes run in order, so later ones dedupe against notes the earlier ones wrote.
        status = max(status, ingest_one(vault, vault / name, out_dir, args.apply))
        print()
    if not args.apply:
        print("preview only; rerun with --apply to write")
    return status


if __name__ == "__main__":
    raise SystemExit(main())

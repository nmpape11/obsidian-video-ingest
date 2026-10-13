"""Command-line entry point: video-ingest."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .notes import apply_plan, plan_ingest

DEFAULT_INBOX = "00 Inbox/Inbox.md"
DEFAULT_OUT = "10 Saved Videos"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-ingest",
        description="Create one Obsidian note per TikTok/Instagram link in an inbox note.",
    )
    p.add_argument("--vault", type=Path, required=True, help="vault root directory")
    p.add_argument("--inbox", default=DEFAULT_INBOX, help="inbox note, relative to vault")
    p.add_argument("--out", default=DEFAULT_OUT, help="notes folder, relative to vault")
    p.add_argument("--apply", action="store_true", help="write changes (default: preview)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    vault = args.vault.expanduser()
    inbox = vault / args.inbox
    out_dir = vault / args.out

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
    print(
        f"\n{len(plan.to_create)} new, {len(plan.duplicates)} duplicate, "
        f"{len(unparsed)} unparsed"
    )

    if not args.apply:
        print("preview only; rerun with --apply to write")
        return 0
    if not plan.to_create and not plan.duplicates:
        print("nothing to do")
        return 0

    apply_plan(plan, inbox, date.today())
    print(f"wrote {len(plan.to_create)} notes; inbox backed up to {inbox.name}.bak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line entry point: video-fetch (stage 2)."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path

from . import frontmatter
from .config import ConfigError, FetchConfig, load_config
from .fetch import Fetcher, YtDlpFetcher
from .notes import with_fetch_result
from .vault import VaultError, notes_dir, pending_notes, write_atomic


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-fetch",
        description="Fetch caption + transcript for video notes that haven't been fetched yet.",
    )
    p.add_argument("--config", type=Path, help="TOML config (default: ./config.toml if present)")
    p.add_argument("--vault", type=Path, help="vault root directory")
    p.add_argument("--out", help="notes folder relative to vault")
    p.add_argument("--apply", action="store_true", help="fetch and write (default: preview)")
    p.add_argument("--limit", type=int, help="process at most N notes")
    p.add_argument("--retry-failed", action="store_true", help="also retry fetch_status: failed")
    p.add_argument("--model", help="Whisper model: tiny, base, small, medium, large-v3, ...")
    p.add_argument("--language", help="spoken language code, e.g. en (default: auto-detect)")
    p.add_argument("--cookies", help="Netscape cookies.txt file (often needed for Instagram)")
    p.add_argument("--cookies-from-browser", help="e.g. chrome or firefox")
    p.add_argument("--sleep", type=float, help="seconds between videos (default: 2)")
    return p


def main(
    argv: list[str] | None = None,
    make_fetcher: Callable[[FetchConfig], Fetcher] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        out_dir = notes_dir(args.vault, args.out, cfg)
    except VaultError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    fcfg = replace(
        cfg.fetch,
        whisper_model=args.model or cfg.fetch.whisper_model,
        language=args.language or cfg.fetch.language,
        cookies_file=args.cookies or cfg.fetch.cookies_file,
        cookies_from_browser=args.cookies_from_browser or cfg.fetch.cookies_from_browser,
        sleep=cfg.fetch.sleep if args.sleep is None else args.sleep,
    )

    todo = pending_notes(out_dir, "fetch_status", args.retry_failed)
    if args.limit is not None:
        todo = todo[: args.limit]
    if not args.apply:
        for path in todo:
            print(f"~ {path.relative_to(out_dir)}")
        print(f"\n{len(todo)} to fetch; preview only, rerun with --apply")
        return 0
    if not todo:
        print("nothing to fetch")
        return 0

    try:
        fetcher = (make_fetcher or _default_fetcher)(fcfg)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    ok = failed = 0
    for i, path in enumerate(todo, 1):
        if i > 1 and fcfg.sleep:
            time.sleep(fcfg.sleep)
        url = frontmatter.get(path.read_text(encoding="utf-8"), "url")
        print(f"[{i}/{len(todo)}] {path.relative_to(out_dir)} ... ", end="", flush=True)
        result = fetcher.fetch(url)
        # Re-read so edits made in Obsidian while fetching aren't clobbered.
        write_atomic(
            path, with_fetch_result(path.read_text(encoding="utf-8"), result, date.today())
        )
        if result.ok:
            ok += 1
            print(f"ok ({result.transcript_source})")
        else:
            failed += 1
            print(f"FAILED: {result.error}")

    print(f"\n{ok} ok, {failed} failed")
    if failed:
        print("retry later with --retry-failed (Instagram usually needs --cookies)")
    return 0


def _default_fetcher(fcfg: FetchConfig) -> Fetcher:
    return YtDlpFetcher(
        whisper_model=fcfg.whisper_model,
        language=fcfg.language,
        cookies_file=fcfg.cookies_file,
        cookies_from_browser=fcfg.cookies_from_browser,
    )


if __name__ == "__main__":
    raise SystemExit(main())

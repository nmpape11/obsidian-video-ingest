"""Command-line entry point: video-ocr (stage 2b)."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from . import frontmatter
from .config import Config, ConfigError, load_config
from .notes import TRANSCRIPT_TITLE, callout_text, with_ocr_result
from .ocr_media import Reader
from .vault import VaultError, notes_dir, pending_notes, write_atomic


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-ocr",
        description="Read on-screen text (slides and video frames) for fetched video notes.",
    )
    p.add_argument("--config", type=Path, help="TOML config (default: ./config.toml if present)")
    p.add_argument("--vault", type=Path, help="vault root directory")
    p.add_argument("--out", help="notes folder relative to vault")
    p.add_argument("--apply", action="store_true", help="read and write (default: preview)")
    p.add_argument("--limit", type=int, help="process at most N notes")
    p.add_argument("--retry-failed", action="store_true", help="also retry ocr_status: failed")
    p.add_argument("--fps", type=float, help="video frames to read per second (default: 1)")
    p.add_argument("--sleep", type=float, help="seconds between videos (default: 2)")
    return p


def main(
    argv: list[str] | None = None, make_reader: Callable[[Config], Reader] | None = None
) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        out_dir = notes_dir(args.vault, args.out, cfg)
    except (ConfigError, VaultError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.fps is not None and args.fps <= 0:
        print("error: --fps must be positive", file=sys.stderr)
        return 2
    cfg.ocr = replace(
        cfg.ocr,
        fps=args.fps or cfg.ocr.fps,
        sleep=cfg.ocr.sleep if args.sleep is None else args.sleep,
    )

    # Fetch first: it confirms the video is reachable and provides the transcript
    # used to skip burned-in subtitles.
    todo = pending_notes(out_dir, "ocr_status", args.retry_failed, {"fetch_status": "ok"})
    if args.limit is not None:
        todo = todo[: args.limit]
    if not args.apply:
        for path in todo:
            print(f"~ {path.relative_to(out_dir)}")
        print(f"\n{len(todo)} to read; preview only, rerun with --apply")
        return 0
    if not todo:
        print("nothing to read (notes need fetch_status: ok first)")
        return 0

    try:
        reader = (make_reader or _default_reader)(cfg)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    ok = failed = 0
    for i, path in enumerate(todo, 1):
        if i > 1 and cfg.ocr.sleep:
            time.sleep(cfg.ocr.sleep)
        text = path.read_text(encoding="utf-8")
        url = frontmatter.get(text, "url")
        author = frontmatter.get(text, "author")
        print(f"[{i}/{len(todo)}] {path.relative_to(out_dir)} ... ", end="", flush=True)
        result = reader.read(
            url, callout_text(text, TRANSCRIPT_TITLE), {author} if author else set()
        )
        # Re-read so edits made in Obsidian meanwhile aren't clobbered.
        write_atomic(path, with_ocr_result(path.read_text(encoding="utf-8"), result))
        if result.ok:
            ok += 1
            print(f"ok ({result.source}, {len(result.lines)} lines from {result.images} images)")
        else:
            failed += 1
            print(f"FAILED: {result.error}")

    print(f"\n{ok} ok, {failed} failed")
    if failed:
        print("retry later with --retry-failed")
    return 0


def _default_reader(cfg: Config) -> Reader:
    from .ocr_media import YtDlpOcr

    return YtDlpOcr(
        fps=cfg.ocr.fps,
        threads=cfg.ocr.threads or None,
        min_score=cfg.ocr.min_score,
        cookies_file=cfg.fetch.cookies_file,
        cookies_from_browser=cfg.fetch.cookies_from_browser,
    )


if __name__ == "__main__":
    raise SystemExit(main())

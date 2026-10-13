"""Command-line entry point: video-enrich (stage 3)."""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path

from . import frontmatter
from .config import EFFORTS, Config, ConfigError, load_config
from .enrich import Enricher
from .notes import note_sources, with_enrichment
from .vault import VaultError, notes_dir, pending_notes, write_atomic

MAX_KNOWN_TAGS = 150


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-enrich",
        description="Fill summary, key points, category and tags with Claude (text only).",
    )
    p.add_argument("--config", type=Path, help="TOML config (default: ./config.toml if present)")
    p.add_argument("--vault", type=Path, help="vault root directory")
    p.add_argument("--out", help="notes folder relative to vault")
    p.add_argument("--apply", action="store_true", help="call Claude and write (default: preview)")
    p.add_argument("--limit", type=int, help="process at most N notes")
    p.add_argument("--retry-failed", action="store_true", help="also retry enrich_status: failed")
    p.add_argument("--model", help="Claude model id (default: claude-opus-5-5)")
    p.add_argument("--effort", choices=sorted(EFFORTS), help="default: low")
    p.add_argument(
        "--no-ocr", action="store_true", help="don't wait for video-ocr (ocr_status) first"
    )
    return p


def tag_counts(out_dir: Path) -> Counter[str]:
    """How often each tag is used across notes, to nudge Claude toward existing spellings."""
    tags: Counter[str] = Counter()
    for path in sorted(out_dir.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(out_dir).parts):
            continue
        try:
            tags.update(
                t.lower() for t in frontmatter.get_list(path.read_text(encoding="utf-8"), "tags")
            )
        except (frontmatter.FrontmatterError, UnicodeDecodeError):
            continue
    return tags


def main(
    argv: list[str] | None = None, make_enricher: Callable[[Config], Enricher] | None = None
) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        out_dir = notes_dir(args.vault, args.out, cfg)
    except (ConfigError, VaultError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    cfg.enrich.model = args.model or cfg.enrich.model
    cfg.enrich.effort = args.effort or cfg.enrich.effort

    require: dict[str, str | set[str]] = {"fetch_status": "ok", "processed": "false"}
    if not args.no_ocr:
        # On-screen text often carries the actual recipe; enrich after OCR has run.
        require["ocr_status"] = {"ok", "failed"}
    todo = pending_notes(out_dir, "enrich_status", args.retry_failed, require)
    if args.limit is not None:
        todo = todo[: args.limit]
    if not args.apply:
        for path in todo:
            print(f"~ {path.relative_to(out_dir)}")
        print(
            f"\n{len(todo)} to enrich with {cfg.enrich.model} (effort {cfg.enrich.effort}); "
            "preview only, rerun with --apply"
        )
        return 0
    if not todo:
        print("nothing to enrich (notes need fetch_status: ok and ocr_status, see --no-ocr)")
        return 0

    try:
        enricher = (make_enricher or _default_enricher)(cfg)
    except Exception as exc:  # missing package or credentials
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Categories are a fixed list, so queries by category stay exact; tags are free-form.
    categories = cfg.enrich.categories
    tags = tag_counts(out_dir)
    ok = failed = 0
    for i, path in enumerate(todo, 1):
        if i > 1 and cfg.enrich.sleep:
            time.sleep(cfg.enrich.sleep)
        sources = note_sources(path.read_text(encoding="utf-8"), path.stem)
        print(f"[{i}/{len(todo)}] {path.relative_to(out_dir)} ... ", end="", flush=True)
        known_tags = [t for t, _ in tags.most_common(MAX_KNOWN_TAGS)]
        try:
            result = enricher.enrich(sources, categories, known_tags)
        except Exception as exc:  # fatal setup errors (auth, unknown model) stop the run
            print(f"\nerror: {type(exc).__name__}: {exc}", file=sys.stderr)
            print("stopping; check ANTHROPIC_API_KEY and the model name", file=sys.stderr)
            return 2
        # Re-read so edits made in Obsidian meanwhile aren't clobbered.
        text, kept = with_enrichment(path.read_text(encoding="utf-8"), result, date.today())
        write_atomic(path, text)
        if not result.ok:
            failed += 1
            print(f"FAILED: {result.error}")
            continue
        ok += 1
        tags.update(result.tags)
        note = f"; kept your {', '.join(kept)}" if kept else ""
        print(f"ok [{', '.join(result.categories)}] {', '.join(result.tags)}{note}")

    print(f"\n{ok} ok, {failed} failed")
    if failed:
        print("retry later with --retry-failed")
    return 0


def _default_enricher(cfg: Config) -> Enricher:
    from .enrich_claude import ClaudeEnricher

    return ClaudeEnricher(model=cfg.enrich.model, effort=cfg.enrich.effort)


if __name__ == "__main__":
    raise SystemExit(main())

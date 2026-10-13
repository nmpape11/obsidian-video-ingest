# CLAUDE.md

Pipeline that turns TikTok/Instagram links saved in Obsidian inbox notes into one
searchable note per video. Code lives here; the Obsidian vault is **not** under git.

## Commands

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev,ocr]"   # ocr includes fetch
.venv/bin/pytest                      # tests
.venv/bin/ruff check . && .venv/bin/ruff format .
.venv/bin/video-ingest                # preview using ./config.toml
.venv/bin/video-ingest --apply        # write notes, trim inbox
.venv/bin/video-fetch                 # preview notes still to fetch
.venv/bin/video-fetch --apply --limit 3
.venv/bin/video-fetch --apply --retry-failed
.venv/bin/video-ocr --apply           # on-screen text, after fetch
```

## Layout

- `src/video_ingest/inbox.py` — line parsing, platform detection, `normalize_url` (dedupe key)
- `src/video_ingest/notes.py` — filename cleanup, note rendering, plan/apply
- `src/video_ingest/config.py` — `config.toml` loading; CLI flags override it
- `src/video_ingest/cli.py` — `video-ingest` entry point
- `src/video_ingest/frontmatter.py` — line-based get/set of frontmatter keys (no YAML lib)
- `src/video_ingest/fetch.py` — yt-dlp + faster-whisper `YtDlpFetcher`, VTT/caption helpers
- `src/video_ingest/fetch_cli.py` — `video-fetch` entry point
- `src/video_ingest/ocr.py` — pure OCR-line cleanup (`consolidate`): dedupe, noise, transcript skip
- `src/video_ingest/ocr_media.py` — slide/frame download + RapidOCR (`YtDlpOcr`)
- `src/video_ingest/ocr_cli.py` — `video-ocr` entry point
- `src/video_ingest/vault.py` — shared `notes_dir` / `pending_notes` / `write_atomic`
- `templates/Video.md` — Obsidian template for manual notes
- `tests/fixtures/vault/` — fake vault with placeholder URLs

## Pipeline stages

1. **Ingest** (done): inbox → one note per video, `processed: false`. No network, no AI.
2. **Fetch** (done): caption + transcript via yt-dlp; faster-whisper fallback. Records
   `fetch_status: failed` and moves on. Never re-fetches (`fetch_status` set = done).
2b. **OCR** (done): on-screen text. Slideshows: every slide image (URLs from TikTok page
   JSON). Videos: 1 fps frames. Needs `fetch_status: ok`; `ocr_status` set = done.
3. **Enrich** (todo): Claude API fills summary, key points, category, tags; sets
   `processed: true`.
4. **Query**: frontmatter filtering / Claude reading the folder. Embeddings only if needed.

Each stage is a separate rerunnable command that reads and writes the vault.

## Note schema (keep in sync)

`url`, `platform` (`tiktok`|`instagram`), `source_title`, `created` (YYYY-MM-DD),
`category` (list of `"[[Wikilink]]"`), `tags` (list), `status` (`to-try`|`tried`|`keeper`),
`processed` (bool). Body: `## Summary`, `## Key points`.
Added by fetch: `author`, `duration` (s), `uploaded`, `transcript_source`
(`subtitles`|`whisper`|`none`), `fetch_status` (`ok`|`failed`), `fetched`, `fetch_error`,
and a `## Source` section with collapsed `[!info]- Caption` / `[!quote]- Transcript` callouts.
Added by OCR: `ocr_status` (`ok`|`failed`), `ocr_source` (`slides`|`frames`|`none`),
`ocr_error`, and a `[!abstract]- On-screen text` callout (list) at the end of Source.
`render_note` and `templates/Video.md` must agree; `tests/test_template.py` enforces it.

## yt-dlp gotchas

- Stored URLs drop `www.`; always fetch via `fetchable_url()` (extractors need `www.`, and
  TikTok `/photo/<id>` must become `/video/<id>`).
- TikTok needs browser impersonation (`curl-cffi`), else "Unexpected response from webpage".
- TikTok format `audio` is the background music, never the speaker. Slideshows only have it.
- `av<19` is pinned: PyAV 19 broke faster-whisper 1.2's `av.open(metadata_errors=...)`.
- Unit tests never hit the network; `video-fetch`/`video-ocr` take injectable fetchers/readers.

## OCR gotchas

- Image-hash frame dedupe doesn't work on cooking videos (camera always moves); dedupe is
  text-based in `consolidate`. Never merge lines whose digits differ (quantities).
- RapidOCR: ~6 threads beats the all-core default; `use_cls=False` and `Det.limit_type=max`
  / `limit_side_len=960` cut ~0.45s to ~0.3s per frame with identical text.
- Video format: h264 muxed <=1024px. A `res:` sort picked TikTok h265 720p, which 403'd.
- Known misses: fraction glyphs (½ ¼), merged words, appliance/brand labels. Left for
  stage 3 rather than more heuristics.

## Rules

- **Never run `--apply` against the real vault while developing.** Use `sandbox/`
  (gitignored), a copy of the vault's inbox files. Preview is the default for a reason.
- Never commit real links, personal vault content, cookies or `config.toml`.
- Ingest must never lose a link: unparseable lines stay in the inbox, notes are opened
  with mode `"x"` (no overwrite), and the inbox is backed up to `.bak` before rewriting.
- Runtime is stdlib-only for stage 1; add dependencies per stage as optional extras
  (`fetch` for stage 2, `ocr` for 2b).
- Small, focused commits with conventional-commit prefixes (`feat`, `fix`, `test`, ...).
  Work on `dev`; `main` is for merges.

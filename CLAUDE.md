# CLAUDE.md

Pipeline that turns TikTok/Instagram links saved in Obsidian inbox notes into one
searchable note per video. Code lives here; the Obsidian vault is **not** under git.

## Commands

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                      # tests
.venv/bin/ruff check . && .venv/bin/ruff format .
.venv/bin/video-ingest                # preview using ./config.toml
.venv/bin/video-ingest --apply        # write notes, trim inbox
```

## Layout

- `src/video_ingest/inbox.py` — line parsing, platform detection, `normalize_url` (dedupe key)
- `src/video_ingest/notes.py` — filename cleanup, note rendering, plan/apply
- `src/video_ingest/config.py` — `config.toml` loading; CLI flags override it
- `src/video_ingest/cli.py` — `video-ingest` entry point
- `templates/Video.md` — Obsidian template for manual notes
- `tests/fixtures/vault/` — fake vault with placeholder URLs

## Pipeline stages

1. **Ingest** (done): inbox → one note per video, `processed: false`. No network, no AI.
2. **Fetch** (todo): caption + transcript via yt-dlp; faster-whisper fallback. Record
   `fetch_status: failed` and move on rather than blocking. Never re-fetch.
3. **Enrich** (todo): Claude API fills summary, key points, category, tags; sets
   `processed: true`.
4. **Query**: frontmatter filtering / Claude reading the folder. Embeddings only if needed.

Each stage is a separate rerunnable command that reads and writes the vault.

## Note schema (keep in sync)

`url`, `platform` (`tiktok`|`instagram`), `source_title`, `created` (YYYY-MM-DD),
`category` (list of `"[[Wikilink]]"`), `tags` (list), `status` (`to-try`|`tried`|`keeper`),
`processed` (bool). Body: `## Summary`, `## Key points`.
`render_note` and `templates/Video.md` must agree; `tests/test_template.py` enforces it.

## Rules

- **Never run `--apply` against the real vault while developing.** Use `sandbox/`
  (gitignored), a copy of the vault's inbox files. Preview is the default for a reason.
- Never commit real links, personal vault content, cookies or `config.toml`.
- Ingest must never lose a link: unparseable lines stay in the inbox, notes are opened
  with mode `"x"` (no overwrite), and the inbox is backed up to `.bak` before rewriting.
- Runtime is stdlib-only for stage 1; add dependencies per stage as optional extras.
- Small, focused commits with conventional-commit prefixes (`feat`, `fix`, `test`, ...).
  Work on `dev`; `main` is for merges.

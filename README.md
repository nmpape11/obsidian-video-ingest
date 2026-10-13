# obsidian-video-ingest

> Work in progress — full docs coming soon.

Turns saved TikTok / Instagram links from an Obsidian inbox note into one
searchable note per video.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,all]"
cp config.example.toml config.toml   # then edit vault/inboxes
video-ingest           # preview
video-ingest --apply   # one note per inbox link
video-fetch --apply    # add caption + transcript to each note
video-ocr --apply      # add on-screen text (slides, video overlays)
export ANTHROPIC_API_KEY=...   # from console.anthropic.com (billed per token, not Pro)
video-enrich --apply   # Claude fills summary, key points, category, tags
```

# obsidian-video-ingest

> Work in progress — full docs coming soon.

Turns saved TikTok / Instagram links from an Obsidian inbox note into one
searchable note per video.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
video-ingest --vault ./sandbox --inbox "00 Inbox/tiktok.md"           # preview
video-ingest --vault ./sandbox --inbox "00 Inbox/tiktok.md" --apply   # write
```

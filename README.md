# obsidian-video-ingest

> Work in progress — full docs coming soon.

Turns saved TikTok / Instagram links from an Obsidian inbox note into one
searchable note per video.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.toml config.toml   # then edit vault/inboxes
video-ingest           # preview
video-ingest --apply   # write
```

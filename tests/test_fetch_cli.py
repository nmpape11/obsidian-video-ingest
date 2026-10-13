from datetime import date

import pytest

from video_ingest import frontmatter
from video_ingest.fetch import FetchResult
from video_ingest.fetch_cli import main
from video_ingest.notes import with_fetch_result
from video_ingest.vault import pending_notes

NOTE = """---
url: {url}
platform: tiktok
processed: false
---

## Summary


## Key points

-
"""
OK = FetchResult(
    ok=True,
    caption="Title\n- 1 cup rice",
    transcript="hello world",
    transcript_source="whisper",
    author="chef",
    duration=64,
    uploaded=date(2024, 1, 2),
)


class FakeFetcher:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        return self.results.get(url, OK)


@pytest.fixture
def vault(tmp_path):
    notes = tmp_path / "vault" / "notes"
    notes.mkdir(parents=True)
    for name in ("a", "b", "c"):
        (notes / f"{name}.md").write_text(NOTE.format(url=f"https://tiktok.com/@x/video/{name}"))
    (notes / "no-frontmatter.md").write_text("just text\n")
    return tmp_path / "vault"


def run(vault, fetcher, *extra):
    argv = ["--vault", str(vault), "--out", "notes", "--sleep", "0", *extra]
    return main(argv, make_fetcher=lambda cfg: fetcher)


def status(vault, name):
    return frontmatter.get((vault / "notes" / f"{name}.md").read_text(), "fetch_status")


def test_with_fetch_result_success():
    out = with_fetch_result(NOTE.format(url="u"), OK, date(2026, 1, 1))
    assert frontmatter.get(out, "fetch_status") == "ok"
    assert frontmatter.get(out, "author") == "chef"
    assert frontmatter.get(out, "uploaded") == "2024-01-02"
    assert "\n## Source\n\n> [!info]- Caption\n> Title\n> - 1 cup rice\n" in out
    assert "> [!quote]- Transcript (whisper)\n> hello world\n" in out
    # A second write updates frontmatter but never duplicates the Source section.
    assert with_fetch_result(out, OK, date(2026, 1, 1)).count("## Source") == 1


def test_with_fetch_result_failure_then_success_clears_error():
    failed = with_fetch_result(
        NOTE.format(url="u"), FetchResult(ok=False, error="blocked"), date(2026, 1, 1)
    )
    assert frontmatter.get(failed, "fetch_error") == "blocked"
    assert "## Source" not in failed
    fixed = with_fetch_result(failed, OK, date(2026, 1, 2))
    assert frontmatter.get(fixed, "fetch_error") is None
    assert frontmatter.get(fixed, "fetch_status") == "ok"


def test_preview_does_not_fetch(vault):
    fetcher = FakeFetcher({})
    assert run(vault, fetcher) == 0
    assert fetcher.calls == []
    assert status(vault, "a") is None


def test_apply_fetches_pending_and_records_failures(vault):
    bad = "https://tiktok.com/@x/video/b"
    fetcher = FakeFetcher({bad: FetchResult(ok=False, error="nope")})
    assert run(vault, fetcher, "--apply") == 0
    assert len(fetcher.calls) == 3
    assert [status(vault, n) for n in "abc"] == ["ok", "failed", "ok"]


def test_never_refetches_and_retry_failed_only_retries_failures(vault):
    bad = "https://tiktok.com/@x/video/b"
    run(vault, FakeFetcher({bad: FetchResult(ok=False, error="nope")}), "--apply")

    again = FakeFetcher({})
    run(vault, again, "--apply")
    assert again.calls == []

    retry = FakeFetcher({})
    run(vault, retry, "--apply", "--retry-failed")
    assert retry.calls == [bad]
    assert status(vault, "b") == "ok"


def test_limit(vault):
    fetcher = FakeFetcher({})
    run(vault, fetcher, "--apply", "--limit", "2")
    assert len(fetcher.calls) == 2


def test_pending_skips_hidden_dirs(vault):
    hidden = vault / "notes" / ".trash"
    hidden.mkdir()
    (hidden / "d.md").write_text(NOTE.format(url="https://tiktok.com/@x/video/d"))
    assert [p.stem for p in pending_notes(vault / "notes", "fetch_status", False)] == [
        "a",
        "b",
        "c",
    ]


def test_missing_notes_folder_errors(tmp_path):
    assert main(["--vault", str(tmp_path), "--out", "nope"]) == 2


def test_fetch_config_from_toml(vault, tmp_path):
    (tmp_path / "config.toml").write_text(
        f'vault = "{vault}"\nout = "notes"\n'
        '[fetch]\nwhisper_model = "small"\nlanguage = ""\nsleep = 0\n'
    )
    seen = {}

    def factory(cfg):
        seen["cfg"] = cfg
        return FakeFetcher({})

    assert main(["--apply", "--limit", "1"], make_fetcher=factory) == 0
    assert seen["cfg"].whisper_model == "small"
    assert seen["cfg"].language is None
    assert seen["cfg"].sleep == 0


def test_pending_require_filters(vault):
    notes = vault / "notes"
    a = notes / "a.md"
    a.write_text(frontmatter.set_fields(a.read_text(), {"fetch_status": "ok"}))
    assert [p.stem for p in pending_notes(notes, "ocr_status", False, {"fetch_status": "ok"})] == [
        "a"
    ]

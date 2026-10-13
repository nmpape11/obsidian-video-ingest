import pytest

from video_ingest import frontmatter
from video_ingest.notes import append_to_section, callout_text, with_ocr_result
from video_ingest.ocr import OcrResult
from video_ingest.ocr_cli import main

NOTE = """---
url: https://tiktok.com/@x/video/{name}
author: chef
fetch_status: {status}
---

## Summary


## Source

> [!info]- Caption
> Pasta

> [!quote]- Transcript (whisper)
> hello there
> general kenobi
"""
LINES = OcrResult(ok=True, lines=["1 cup rice", "Add salt"], source="frames", images=30)


class FakeReader:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    def read(self, url, transcript="", handles=None):
        self.calls.append((url, transcript, handles))
        return self.results.get(url, LINES)


@pytest.fixture
def vault(tmp_path):
    notes = tmp_path / "vault" / "notes"
    notes.mkdir(parents=True)
    for name, status in (("a", "ok"), ("b", "ok"), ("c", "failed")):
        (notes / f"{name}.md").write_text(NOTE.format(name=name, status=status))
    return tmp_path / "vault"


def run(vault, reader, *extra):
    argv = ["--vault", str(vault), "--out", "notes", "--sleep", "0", *extra]
    return main(argv, make_reader=lambda cfg: reader)


def note(vault, name):
    return (vault / "notes" / f"{name}.md").read_text()


def test_callout_text():
    text = NOTE.format(name="a", status="ok")
    assert callout_text(text, "Transcript") == "hello there\ngeneral kenobi"
    assert callout_text(text, "Caption") == "Pasta"
    assert callout_text(text, "On-screen text") == ""


def test_append_to_section_goes_before_next_heading():
    text = "---\na: 1\n---\n\n## Source\n\n> x\n\n\n## Mine\n\nnotes\n"
    out = append_to_section(text, "## Source", "> y")
    assert out == "---\na: 1\n---\n\n## Source\n\n> x\n\n> y\n\n## Mine\n\nnotes\n"


def test_append_to_section_creates_missing_section():
    assert append_to_section("---\na: 1\n---\n\nbody\n", "## Source", "> y") == (
        "---\na: 1\n---\n\nbody\n\n## Source\n\n> y\n"
    )


def test_with_ocr_result_success_is_idempotent():
    out = with_ocr_result(NOTE.format(name="a", status="ok"), LINES)
    assert frontmatter.get(out, "ocr_status") == "ok"
    assert frontmatter.get(out, "ocr_source") == "frames"
    assert out.endswith("> [!abstract]- On-screen text (frames)\n> - 1 cup rice\n> - Add salt\n")
    assert with_ocr_result(out, LINES) == out


def test_with_ocr_result_no_lines_and_failure():
    empty = with_ocr_result(NOTE.format(name="a", status="ok"), OcrResult(ok=True))
    assert frontmatter.get(empty, "ocr_source") == "none"
    assert "On-screen text" not in empty
    failed = with_ocr_result(empty, OcrResult(ok=False, error="403"))
    assert frontmatter.get(failed, "ocr_status") == "failed"
    assert frontmatter.get(failed, "ocr_error") == "403"


def test_preview_does_not_read(vault):
    reader = FakeReader()
    assert run(vault, reader) == 0
    assert reader.calls == []


def test_apply_reads_only_fetched_notes_and_passes_context(vault):
    reader = FakeReader()
    assert run(vault, reader, "--apply") == 0
    assert [c[0].rsplit("/", 1)[1] for c in reader.calls] == ["a", "b"]  # c not fetched
    _, transcript, handles = reader.calls[0]
    assert transcript == "hello there\ngeneral kenobi"
    assert handles == {"chef"}
    assert "> - 1 cup rice" in note(vault, "a")


def test_never_rereads_and_retry_failed(vault):
    bad = "https://tiktok.com/@x/video/b"
    run(vault, FakeReader({bad: OcrResult(ok=False, error="nope")}), "--apply")
    again = FakeReader()
    run(vault, again, "--apply")
    assert again.calls == []
    retry = FakeReader()
    run(vault, retry, "--apply", "--retry-failed")
    assert [c[0] for c in retry.calls] == [bad]


def test_rejects_bad_fps(vault):
    assert run(vault, FakeReader(), "--fps", "0") == 2

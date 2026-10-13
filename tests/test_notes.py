import shutil
from datetime import date
from pathlib import Path

import pytest

from video_ingest.cli import main
from video_ingest.notes import existing_urls, safe_filename

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"
INBOX = "00 Inbox/tiktok.md"
OUT = "10 Saved Videos"


@pytest.fixture
def vault(tmp_path):
    dest = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, dest)
    return dest


def run(vault, *extra):
    return main(["--vault", str(vault), "--inbox", INBOX, "--out", OUT, *extra])


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Best RDL cue 🏋️", "Best RDL cue"),
        ("Pasta: 5-minute hack?", "Pasta 5-minute hack"),
        ("a/b\\c|d", "a b c d"),
        ("🔥🔥", ""),
    ],
)
def test_safe_filename(title, expected):
    assert safe_filename(title) == expected


def test_safe_filename_truncates_on_word_boundary():
    name = safe_filename("word " * 40)
    assert len(name) <= 80
    assert not name.endswith(" ")


def test_preview_writes_nothing(vault):
    before = (vault / INBOX).read_text()
    assert run(vault) == 0
    assert not (vault / OUT).exists()
    assert (vault / INBOX).read_text() == before


def test_apply_creates_notes_and_trims_inbox(vault):
    assert run(vault, "--apply") == 0

    notes = sorted(p.name for p in (vault / OUT).glob("*.md"))
    assert notes == [
        "Best RDL cue.md",
        "Morning routine.md",
        "Pasta 5-minute hack.md",
        "tiktok ZMexample.md",
    ]

    note = (vault / OUT / "Pasta 5-minute hack.md").read_text()
    assert "url: https://instagram.com/reel/ExAmPlE123\n" in note
    assert 'source_title: "Pasta: 5-minute hack?"\n' in note
    assert f"created: {date.today().isoformat()}\n" in note
    assert "processed: false\n" in note

    inbox = (vault / INBOX).read_text()
    assert "tiktok.com" not in inbox and "instagram.com" not in inbox
    assert "example.com/article" in inbox
    assert (vault / (INBOX + ".bak")).is_file()


def test_rerun_is_idempotent(vault):
    run(vault, "--apply")
    shutil.copy(vault / (INBOX + ".bak"), vault / INBOX)  # same links again
    run(vault, "--apply")
    assert len(list((vault / OUT).glob("*.md"))) == 4


def test_filename_collision_gets_suffix(vault):
    (vault / INBOX).write_text(
        "- Same https://tiktok.com/@a/video/1\n- Same https://tiktok.com/@a/video/2\n"
    )
    run(vault, "--apply")
    assert sorted(p.name for p in (vault / OUT).glob("*.md")) == ["Same 2.md", "Same.md"]


def test_existing_urls_reads_frontmatter(tmp_path):
    (tmp_path / "n.md").write_text("---\nurl: https://www.tiktok.com/@a/video/1/?x=1\n---\n")
    (tmp_path / "plain.md").write_text("url: https://tiktok.com/@a/video/2\n")
    assert existing_urls(tmp_path) == {"https://tiktok.com/@a/video/1"}


def test_missing_inbox_errors(tmp_path):
    assert main(["--vault", str(tmp_path)]) == 2

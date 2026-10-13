import pytest

from video_ingest import frontmatter
from video_ingest.enrich import EnrichResult
from video_ingest.enrich_cli import main, vocabulary

NOTE = """---
url: https://tiktok.com/@x/video/{name}
platform: tiktok
category: {category}
tags: {tags}
processed: {processed}
fetch_status: ok
{ocr}---

## Summary


## Key points

- 

## Source

> [!info]- Caption
> caption {name}
"""


def write(notes, name, processed="false", ocr="ocr_status: ok\n", category="[]", tags="[]"):
    (notes / f"{name}.md").write_text(
        NOTE.format(name=name, processed=processed, ocr=ocr, category=category, tags=tags)
    )


class FakeEnricher:
    def __init__(self, results=None, exc=None):
        self.results, self.exc, self.calls = results or {}, exc, []

    def enrich(self, sources, known_categories, known_tags):
        self.calls.append((sources, list(known_categories), list(known_tags)))
        if self.exc:
            raise self.exc
        name = sources.caption.split()[-1]
        return self.results.get(
            name,
            EnrichResult(
                ok=True,
                summary=f"About {name}.",
                key_points=["one"],
                categories=["Cooking"],
                tags=[f"tag-{name}"],
                model="claude-opus-5-5",
            ),
        )


@pytest.fixture
def vault(tmp_path):
    notes = tmp_path / "vault" / "notes"
    notes.mkdir(parents=True)
    write(notes, "a")
    write(notes, "b")
    write(notes, "no-ocr", ocr="")
    write(notes, "done", processed="true", category='\n  - "[[Gym]]"', tags="[squat, legs]")
    return tmp_path / "vault"


def run(vault, enricher, *extra):
    return main(["--vault", str(vault), "--out", "notes", *extra], make_enricher=lambda c: enricher)


def read(vault, name):
    return (vault / "notes" / f"{name}.md").read_text()


def test_vocabulary_collects_categories_and_tags(vault):
    cats, tags = vocabulary(vault / "notes", ["Self Help", "gym"])
    assert cats == ["Self Help", "gym"]  # "Gym" from notes is the same category as the seed
    assert tags == {"squat": 1, "legs": 1}


def test_preview_calls_nothing(vault):
    enricher = FakeEnricher()
    assert run(vault, enricher) == 0
    assert enricher.calls == []


def test_apply_enriches_pending_ocr_done_notes(vault):
    enricher = FakeEnricher()
    assert run(vault, enricher, "--apply") == 0
    assert [c[0].caption for c in enricher.calls] == ["caption a", "caption b"]
    assert "About a." in read(vault, "a")
    assert frontmatter.get(read(vault, "a"), "processed") == "true"
    assert frontmatter.get(read(vault, "no-ocr"), "processed") == "false"


def test_vocabulary_grows_during_run(vault):
    enricher = FakeEnricher()
    run(vault, enricher, "--apply")
    _, cats_b, tags_b = enricher.calls[1]
    assert "Cooking" in cats_b and "Gym" in cats_b
    assert "tag-a" in tags_b and "squat" in tags_b


def test_no_ocr_flag_includes_notes_without_ocr(vault):
    enricher = FakeEnricher()
    run(vault, enricher, "--apply", "--no-ocr")
    assert len(enricher.calls) == 3


def test_failures_recorded_and_retried(vault):
    run(vault, FakeEnricher({"b": EnrichResult(ok=False, error="refused by model")}), "--apply")
    assert frontmatter.get(read(vault, "b"), "enrich_status") == "failed"
    again = FakeEnricher()
    run(vault, again, "--apply")
    assert again.calls == []
    retry = FakeEnricher()
    run(vault, retry, "--apply", "--retry-failed")
    assert [c[0].caption for c in retry.calls] == ["caption b"]
    assert frontmatter.get(read(vault, "b"), "processed") == "true"


def test_fatal_error_stops_run_without_touching_notes(vault):
    before = read(vault, "a")
    assert run(vault, FakeEnricher(exc=PermissionError("bad key")), "--apply") == 2
    assert read(vault, "a") == before


def test_enrich_config(vault, tmp_path):
    (tmp_path / "config.toml").write_text(
        f'vault = "{vault}"\nout = "notes"\n'
        '[enrich]\nmodel = "claude-sonnet-5-5"\neffort = "medium"\ncategories = ["Self Help"]\n'
    )
    seen = {}

    def factory(cfg):
        seen["cfg"] = cfg
        return FakeEnricher()

    assert main(["--apply", "--limit", "1"], make_enricher=factory) == 0
    assert (seen["cfg"].enrich.model, seen["cfg"].enrich.effort) == ("claude-sonnet-5-5", "medium")


@pytest.mark.parametrize("body", ['effort = "huge"', 'categories = "Gym"', "sleep = -1"])
def test_bad_enrich_config(tmp_path, body):
    from video_ingest.config import ConfigError, load_config

    path = tmp_path / "c.toml"
    path.write_text(f"[enrich]\n{body}\n")
    with pytest.raises(ConfigError):
        load_config(path)

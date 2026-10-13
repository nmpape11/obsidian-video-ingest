from pathlib import Path

import pytest

from video_ingest.cli import main
from video_ingest.config import DEFAULT_INBOXES, ConfigError, load_config


def test_no_config_file_gives_defaults():
    cfg = load_config(None)
    assert cfg.vault is None
    assert cfg.inboxes == DEFAULT_INBOXES


def test_loads_default_config_from_cwd(tmp_path):
    (tmp_path / "config.toml").write_text('vault = "v"\ninboxes = ["a.md", "b.md"]\nout = "o"\n')
    cfg = load_config(None)
    assert cfg.vault == Path("v")
    assert cfg.inboxes == ["a.md", "b.md"]
    assert cfg.out == "o"


def test_explicit_missing_config_errors(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")


def test_bad_inboxes_type_errors(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('inboxes = "a.md"\n')
    with pytest.raises(ConfigError):
        load_config(path)


def test_example_config_parses():
    example = Path(__file__).parents[1] / "config.example.toml"
    assert load_config(example).inboxes == ["00 Inbox/tiktok.md", "00 Inbox/instagram.md"]


def test_cli_uses_config_and_processes_all_inboxes(tmp_path):
    vault = tmp_path / "vault"
    (vault / "in").mkdir(parents=True)
    (vault / "in" / "tt.md").write_text("- a https://tiktok.com/@a/video/1\n")
    (vault / "in" / "ig.md").write_text(
        "- b https://instagram.com/reel/B\n- a again https://www.tiktok.com/@a/video/1/\n"
    )
    (tmp_path / "config.toml").write_text(
        f'vault = "{vault}"\ninboxes = ["in/tt.md", "in/ig.md"]\nout = "notes"\n'
    )

    assert main(["--apply"]) == 0
    assert sorted(p.name for p in (vault / "notes").glob("*.md")) == ["a.md", "b.md"]
    assert (vault / "in" / "ig.md").read_text() == ""


def test_cli_flag_overrides_config_inboxes(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "only.md").write_text("- x https://tiktok.com/@a/video/9\n")
    (tmp_path / "config.toml").write_text(f'vault = "{vault}"\ninboxes = ["missing.md"]\n')
    assert main(["--inbox", "only.md", "--apply"]) == 0


def test_cli_requires_vault():
    assert main([]) == 2


def test_unknown_fetch_key_errors(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("[fetch]\nwhsiper_model = 'small'\n")
    with pytest.raises(ConfigError, match="whsiper_model"):
        load_config(path)


def test_example_config_fetch_section():
    example = Path(__file__).parents[1] / "config.example.toml"
    fetch = load_config(example).fetch
    assert fetch.whisper_model == "base"
    assert fetch.cookies_file is None

import pytest


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """Keep a developer's local ./config.toml from leaking into tests."""
    monkeypatch.chdir(tmp_path)

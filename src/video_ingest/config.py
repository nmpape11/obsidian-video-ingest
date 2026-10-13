"""Load settings from config.toml, with CLI flags taking precedence."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path("config.toml")
DEFAULT_INBOXES = ["00 Inbox/Inbox.md"]
DEFAULT_OUT = "10 Saved Videos"


class ConfigError(ValueError):
    pass


@dataclass
class FetchConfig:
    whisper_model: str = "base"
    language: str | None = None  # None lets Whisper auto-detect
    cookies_file: str | None = None
    cookies_from_browser: str | None = None
    sleep: float = 2.0  # seconds between videos, to stay under rate limits


@dataclass
class Config:
    vault: Path | None = None
    inboxes: list[str] = field(default_factory=lambda: list(DEFAULT_INBOXES))
    out: str = DEFAULT_OUT
    fetch: FetchConfig = field(default_factory=FetchConfig)


def load_config(path: Path | None) -> Config:
    """Read path, or ./config.toml if it exists. Missing default file is not an error."""
    if path is None:
        if not DEFAULT_CONFIG.is_file():
            return Config()
        path = DEFAULT_CONFIG
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

    cfg = Config()
    if "vault" in data:
        cfg.vault = Path(data["vault"]).expanduser()
    if "inboxes" in data:
        inboxes = data["inboxes"]
        if not isinstance(inboxes, list) or not all(isinstance(i, str) for i in inboxes):
            raise ConfigError("'inboxes' must be a list of strings")
        cfg.inboxes = inboxes
    if "out" in data:
        cfg.out = str(data["out"])
    if "fetch" in data:
        cfg.fetch = _load_fetch(data["fetch"])
    return cfg


def _load_fetch(table: object) -> FetchConfig:
    if not isinstance(table, dict):
        raise ConfigError("[fetch] must be a table")
    known = set(FetchConfig.__dataclass_fields__)
    unknown = set(table) - known
    if unknown:
        raise ConfigError(f"unknown [fetch] keys: {', '.join(sorted(unknown))}")
    fetch = FetchConfig(**{k: v for k, v in table.items() if v != ""})
    if not isinstance(fetch.sleep, int | float) or fetch.sleep < 0:
        raise ConfigError("[fetch] sleep must be a non-negative number")
    return fetch

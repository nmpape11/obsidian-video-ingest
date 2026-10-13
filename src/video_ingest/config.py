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
class Config:
    vault: Path | None = None
    inboxes: list[str] = field(default_factory=lambda: list(DEFAULT_INBOXES))
    out: str = DEFAULT_OUT


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
    return cfg

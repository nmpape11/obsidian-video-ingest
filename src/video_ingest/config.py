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
class OcrConfig:
    fps: float = 1.0  # frames per second of video to read
    threads: int = 0  # OCR threads; 0 = min(6, cores)
    min_score: float = 0.8  # drop OCR lines read with lower confidence
    sleep: float = 2.0


@dataclass
class Config:
    vault: Path | None = None
    inboxes: list[str] = field(default_factory=lambda: list(DEFAULT_INBOXES))
    out: str = DEFAULT_OUT
    fetch: FetchConfig = field(default_factory=FetchConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)


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
        cfg.fetch = _load_table("fetch", FetchConfig, data["fetch"], ["sleep"])
    if "ocr" in data:
        cfg.ocr = _load_table(
            "ocr", OcrConfig, data["ocr"], ["fps", "threads", "min_score", "sleep"]
        )
        if cfg.ocr.fps <= 0:
            raise ConfigError("[ocr] fps must be positive")
    return cfg


def _load_table(name: str, cls: type, table: object, numbers: list[str]):
    """Build a dataclass from a TOML table; "" means "use the default"."""
    if not isinstance(table, dict):
        raise ConfigError(f"[{name}] must be a table")
    unknown = set(table) - set(cls.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"unknown [{name}] keys: {', '.join(sorted(unknown))}")
    obj = cls(**{k: v for k, v in table.items() if v != ""})
    for key in numbers:
        value = getattr(obj, key)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ConfigError(f"[{name}] {key} must be a non-negative number")
    return obj

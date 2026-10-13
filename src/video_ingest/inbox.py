"""Parse inbox lines into video entries and normalize their URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

URL_RE = re.compile(r"https?://[^\s<>()\[\]]+")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
# Leading list markers / checkboxes: "- ", "* ", "1. ", "- [ ] "
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")
# Separators people put between a title and a URL: "Title - url", "Title: url"
TRAILING_SEP_RE = re.compile(r"[\s\-–—:|]+$")
LEADING_SEP_RE = re.compile(r"^[\s\-–—:|]+")

PLATFORM_HOSTS = {
    "tiktok.com": "tiktok",
    "vm.tiktok.com": "tiktok",
    "vt.tiktok.com": "tiktok",
    "instagram.com": "instagram",
    "instagr.am": "instagram",
}


@dataclass(frozen=True)
class Entry:
    url: str
    platform: str
    title: str
    raw: str


def _host(netloc: str) -> str:
    host = netloc.lower().split("@")[-1].split(":")[0]
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host


def detect_platform(url: str) -> str | None:
    host = _host(urlsplit(url).netloc)
    if host in PLATFORM_HOSTS:
        return PLATFORM_HOSTS[host]
    for known, platform in PLATFORM_HOSTS.items():
        if host.endswith("." + known):
            return platform
    return None


def normalize_url(url: str) -> str:
    """Canonical form used for dedupe: https, bare host, no query/fragment/trailing slash.

    TikTok and Instagram query strings are tracking only (igsh, is_from_webapp, _r, ...),
    so dropping them makes the same video shared twice compare equal.
    """
    url = url.rstrip(".,;")
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", _host(parts.netloc), path, "", ""))


def fetchable_url(url: str) -> str:
    """Turn a stored (normalized) URL back into one yt-dlp's extractors match.

    normalize_url drops "www." for dedupe, but the TikTok/Instagram extractors only
    match the www host. TikTok photo slideshows (/photo/<id>) aren't matched at all, but
    the same id resolves via /video/<id>. Short links (vm./vt.tiktok.com) are left alone.
    """
    parts = urlsplit(url)
    host = _host(parts.netloc)
    if host not in ("tiktok.com", "instagram.com"):
        return url
    path = parts.path
    if host == "tiktok.com":
        path = re.sub(r"^(/@[^/]+)/photo/", r"\1/video/", path)
    return urlunsplit(("https", "www." + host, path, "", ""))


def parse_line(line: str) -> Entry | None:
    """Return an Entry for a line holding one supported video URL, else None."""
    md = MD_LINK_RE.search(line)
    if md:
        url, title = md.group(2), md.group(1)
        rest = line[: md.start()] + line[md.end() :]
    else:
        urls = URL_RE.findall(line)
        if len(urls) != 1:
            return None
        url = urls[0]
        before, _, after = line.partition(url)
        title, rest = before, after

    platform = detect_platform(url)
    if platform is None:
        return None

    title = BULLET_RE.sub("", title)
    if not title.strip():
        title = BULLET_RE.sub("", rest)
    title = LEADING_SEP_RE.sub("", TRAILING_SEP_RE.sub("", title)).strip()
    return Entry(url=normalize_url(url), platform=platform, title=title, raw=line)


def parse_inbox(text: str) -> tuple[list[Entry], list[str]]:
    """Split inbox text into parsed entries and lines to keep in the inbox.

    Blank lines and headings are kept; lines with a URL that can't be parsed are kept
    so nothing is ever lost.
    """
    entries: list[Entry] = []
    kept: list[str] = []
    for line in text.splitlines():
        entry = parse_line(line) if URL_RE.search(line) else None
        if entry is None:
            kept.append(line)
        else:
            entries.append(entry)
    return entries, kept
